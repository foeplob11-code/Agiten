"""도구 실행기 — ToolCall 을 실제 시스템 작업으로 수행한다.

안전 원칙(자동화라도 지킨다):
  1) 파일 작업은 workspace 안으로 제한(밖으로 나가면 거부).
  2) 되돌릴 수 없는 도구(CONFIRM_REQUIRED)와 shell.run 은 승인 콜백을 거친다.
     - 대화형: 사람에게 물어봄.  자동/무인: auto_approve 에 든 것만 통과.
  3) shell.run 은 workspace 를 작업디렉토리로, 타임아웃을 걸어 실행.
  4) dry_run 이면 아무것도 실제로 바꾸지 않고 "무엇을 할지"만 돌려준다.

반환값은 학습 데이터와 같은 JSON 문자열({"ok": true, ...}) — 모델에 그대로 되먹인다.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Callable

from ..protocol import ToolCall
from ..toolspec import BY_NAME, CONFIRM_REQUIRED

# shell.run 은 임의 명령이라 확인 대상에 포함(카탈로그엔 없지만 실행층에서 강제)
NEEDS_APPROVAL = set(CONFIRM_REQUIRED) | {"shell.run"}

# 무인 실행 시 위험 신호가 있으면 자동승인에서도 막는다
DANGEROUS_PATTERNS = ("rm -rf /", "mkfs", ":(){", "dd if=", "> /dev/sd", "shutdown", "reboot")

ConfirmCb = Callable[[ToolCall, str], bool]


def _ok(**kw) -> str:
    return json.dumps({"ok": True, **kw}, ensure_ascii=False)


def _err(msg: str, **kw) -> str:
    return json.dumps({"ok": False, "error": msg, **kw}, ensure_ascii=False)


class Executor:
    def __init__(self, workspace: str | Path = "runtime/workspace",
                 confirm_cb: ConfirmCb | None = None,
                 auto_approve: set[str] | None = None,
                 dry_run: bool = False,
                 shell_timeout: int = 30):
        self.ws = Path(workspace).resolve()
        self.ws.mkdir(parents=True, exist_ok=True)
        self.confirm_cb = confirm_cb
        self.auto_approve = auto_approve or set()   # 무인 실행 시 통과시킬 도구
        self.dry_run = dry_run
        self.shell_timeout = shell_timeout
        self.memory: dict[str, str] = {}

    # ------------------------------------------------------------ 진입점
    def execute(self, call: ToolCall) -> str:
        spec = BY_NAME.get(call.name)
        if spec is None:
            return _err(f"알 수 없는 도구: {call.name}")

        # 승인 게이트
        if call.name in NEEDS_APPROVAL and not self.dry_run:
            preview = self._preview(call)
            if not self._approved(call, preview):
                return _err("사용자가 승인하지 않아 실행하지 않았어요.", skipped=True)

        try:
            handler = getattr(self, "_do_" + call.name.replace(".", "_"), None)
            if handler is None:
                return _err(f"아직 실행이 연결되지 않은 도구: {call.name}", not_implemented=True)
            return handler(call.args)
        except Exception as e:  # noqa: BLE001 — 어떤 도구 오류든 모델에 정직히 전달
            return _err(f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------ 승인
    def _approved(self, call: ToolCall, preview: str) -> bool:
        if any(p in json.dumps(call.args, ensure_ascii=False) for p in DANGEROUS_PATTERNS):
            return False  # 위험 패턴은 무인 자동승인 불가
        if call.name in self.auto_approve:
            return True
        if self.confirm_cb is not None:
            return bool(self.confirm_cb(call, preview))
        return False  # 콜백도 없고 자동승인도 아니면 안전하게 거부

    def _preview(self, call: ToolCall) -> str:
        if call.name == "shell.run":
            return f"명령 실행: {call.args.get('cmd', '')}"
        if call.name == "fs.write":
            return f"파일 덮어쓰기: {call.args.get('path', '')}"
        return f"{call.name} 실행 ({call.args})"

    # ------------------------------------------------------------ 경로 안전
    def _safe(self, path: str) -> Path:
        p = (self.ws / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        if self.ws not in p.parents and p != self.ws:
            raise PermissionError(f"작업폴더 밖 접근 거부: {path}")
        return p

    # ------------------------------------------------------------ 터미널
    def _do_shell_run(self, args: dict) -> str:
        cmd = args.get("cmd", "")
        if self.dry_run:
            return _ok(dry_run=True, would_run=cmd)
        r = subprocess.run(cmd, shell=True, cwd=self.ws, capture_output=True,
                           text=True, timeout=self.shell_timeout)
        out = (r.stdout or "")[-2000:]
        return _ok(exit_code=r.returncode, stdout=out, stderr=(r.stderr or "")[-500:])

    def _do_shell_which(self, args: dict) -> str:
        import shutil
        p = shutil.which(args.get("name", ""))
        return _ok(found=bool(p), path=p) if p else _ok(found=False)

    # ------------------------------------------------------------ 파일
    def _do_fs_list(self, args: dict) -> str:
        d = self._safe(args.get("path", "."))
        if not d.exists():
            return _err("경로 없음", path=str(d))
        return _ok(entries=sorted(x.name + ("/" if x.is_dir() else "") for x in d.iterdir()))

    def _do_fs_read(self, args: dict) -> str:
        f = self._safe(args["path"])
        text = f.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        s = int(args.get("start", 1)); e = int(args.get("end", len(lines)))
        return _ok(path=str(f), content="\n".join(lines[s - 1:e]), lines=len(lines))

    def _do_fs_write(self, args: dict) -> str:
        f = self._safe(args["path"])
        if self.dry_run:
            return _ok(dry_run=True, would_write=str(f), bytes=len(args.get("content", "")))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(args.get("content", ""), encoding="utf-8")
        return _ok(path=str(f), bytes=f.stat().st_size)

    def _do_fs_edit(self, args: dict) -> str:
        f = self._safe(args["path"])
        text = f.read_text(encoding="utf-8")
        old, new = args["old"], args["new"]
        if old not in text:
            return _err("찾는 문자열이 없어요", old=old)
        if self.dry_run:
            return _ok(dry_run=True, replaced=text.count(old))
        f.write_text(text.replace(old, new), encoding="utf-8")
        return _ok(path=str(f), replaced=text.count(old))

    def _do_fs_search(self, args: dict) -> str:
        import re
        pat = re.compile(args["pattern"])
        root = self._safe(args.get("path", "."))
        hits = []
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                        if pat.search(line):
                            hits.append({"path": str(p.relative_to(self.ws)), "line": i})
                            if len(hits) >= 50:
                                return _ok(matches=hits, truncated=True)
                except Exception:
                    pass
        return _ok(matches=hits)

    def _do_code_run_tests(self, args: dict) -> str:
        if self.dry_run:
            return _ok(dry_run=True, would_run="pytest")
        r = subprocess.run(["python", "-m", "pytest", "-q", args.get("path", ".")],
                           cwd=self.ws, capture_output=True, text=True,
                           timeout=self.shell_timeout * 4)
        return _ok(exit_code=r.returncode, stdout=(r.stdout or "")[-1500:])

    # ------------------------------------------------------------ 기억(로컬)
    def _do_memory_save(self, args: dict) -> str:
        self.memory[args["key"]] = args["value"]
        return _ok()

    def _do_memory_recall(self, args: dict) -> str:
        q = args.get("query", "")
        hit = next((v for k, v in self.memory.items() if q in k or q in v), None)
        return _ok(hit=hit) if hit else _ok(hit=None)

    # ------------------------------------------------------------ 미연동(향후)
    # email.*, chat.*, cal.*, web.* 는 실제 계정/네트워크 연동이 필요하다.
    # 지금은 명시적으로 "미연동"을 돌려주어 모델이 헛돌지 않게 한다.
    def _stub(self, name: str) -> str:
        return _err(f"'{name}' 는 아직 실제 연동이 안 됐어요. 연동을 붙이면 동작합니다.",
                    not_connected=True)

    def _do_email_search(self, a): return self._stub("email.search")
    def _do_email_read(self, a): return self._stub("email.read")
    def _do_email_draft(self, a): return self._stub("email.draft")
    def _do_email_send(self, a): return self._stub("email.send")
    def _do_chat_unread(self, a): return self._stub("chat.unread")
    def _do_chat_read(self, a): return self._stub("chat.read")
    def _do_chat_send(self, a): return self._stub("chat.send")
    def _do_cal_list(self, a): return self._stub("cal.list")
    def _do_cal_create(self, a): return self._stub("cal.create")
    def _do_web_search(self, a): return self._stub("web.search")
    def _do_web_fetch(self, a): return self._stub("web.fetch")
