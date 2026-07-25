"""Agiten 채팅 서버 — 브라우저에서 자동화 비서와 대화.

표준 라이브러리만 사용(추가 설치 불필요). 학습된 체크포인트가 있으면 모델을 올리고,
없으면 "학습 중" 상태를 돌려준다(학습이 끝나면 새로고침만 하면 됨).

사용:
  python scripts/serve.py                # 기본 runs/smoke-sft/ckpt_last.pt
  python scripts/serve.py --ckpt ... --port 8000
그다음 브라우저에서  http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agiten.protocol import Message  # noqa: E402

STATE = {
    "ready": False, "detail": "모델 로드 중…", "model_name": "",
    "agent": None, "executor": None, "history": None, "lock": threading.Lock(),
}
ARGS = None


def try_load_model():
    """체크포인트가 있으면 모델을 올린다. 없으면 학습 대기 상태로."""
    ckpt = Path(ARGS.ckpt)
    if not ckpt.exists():
        STATE["ready"] = False
        STATE["detail"] = "모델 학습 중… (학습이 끝나면 자동으로 준비돼요)"
        return
    try:
        import torch
        from agiten.model import Agiten, ModelConfig
        from agiten.tokenizer import AgitenTokenizer
        from agiten.runtime.executor import Executor, NEEDS_APPROVAL
        from agiten.runtime.agent import Agent, ModelPolicy

        device = "mps" if torch.backends.mps.is_available() else \
                 ("cuda" if torch.cuda.is_available() else "cpu")
        ck = torch.load(ckpt, map_location=device)
        cfg = ModelConfig(**ck["cfg"])
        model = Agiten(cfg).to(device); model.load_state_dict(ck["model"]); model.eval()
        tok = AgitenTokenizer.load(ARGS.tokenizer)

        ex = Executor(workspace=ARGS.workspace)  # auto_approve 는 요청마다 설정
        policy = ModelPolicy(model, tok, cfg, temperature=ARGS.temperature)
        STATE["executor"] = ex
        STATE["_needs_approval"] = set(NEEDS_APPROVAL)
        # 작은 모델은 짧은 시스템 프롬프트가 문맥을 아껴 안정적(도구는 가중치에 학습됨)
        STATE["agent"] = Agent(policy, ex, max_steps=ARGS.max_steps, with_tools_prompt=False)
        STATE["model_name"] = f"{cfg.n_params()/1e6:.0f}M · {device}"
        STATE["ready"] = True
        STATE["detail"] = "준비됨"
        print(f"[serve] 모델 로드 완료: {STATE['model_name']}")
    except Exception as e:  # noqa: BLE001
        STATE["ready"] = False
        STATE["detail"] = f"로드 실패: {e}"
        print(f"[serve] 로드 실패: {e}")


def run_chat(message: str, allow: bool) -> list[dict]:
    """에이전트를 돌리고 UI용 이벤트 목록을 만든다."""
    events: list[dict] = []

    def on_event(kind, data):
        if kind == "assistant":
            if getattr(data, "think", ""):
                events.append({"kind": "think", "data": data.think})
        elif kind == "call":
            events.append({"kind": "call", "data": {"name": data.name, "args": data.args}})
        elif kind == "result":
            events.append({"kind": "result", "data": data})
        elif kind == "final":
            events.append({"kind": "final", "data": data})

    with STATE["lock"]:
        ex = STATE["executor"]
        ex.auto_approve = STATE["_needs_approval"] if allow else set()
        agent = STATE["agent"]
        agent.on_event = on_event
        STATE["history"] = agent.run(message, STATE["history"])
    return events


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 조용히
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (ROOT / "web" / "chat.html").read_text(encoding="utf-8")
            return self._send(200, html, "text/html; charset=utf-8")
        if self.path == "/status":
            if not STATE["ready"]:
                try_load_model()  # 학습이 끝났을 수 있으니 재시도
            return self._send(200, json.dumps({
                "ready": STATE["ready"], "detail": STATE["detail"],
                "model": STATE["model_name"]}, ensure_ascii=False))
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            payload = {}

        if self.path == "/reset":
            STATE["history"] = None
            return self._send(200, json.dumps({"ok": True}))

        if self.path == "/chat":
            if not STATE["ready"]:
                return self._send(200, json.dumps(
                    {"error": STATE["detail"]}, ensure_ascii=False))
            msg = (payload.get("message") or "").strip()
            if not msg:
                return self._send(200, json.dumps({"events": []}))
            try:
                events = run_chat(msg, bool(payload.get("allow")))
                return self._send(200, json.dumps({"events": events}, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                return self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False))

        return self._send(404, json.dumps({"error": "not found"}))


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="runs/smoke-sft/ckpt_last.pt")
    ap.add_argument("--tokenizer", default="tokenizer.json")
    ap.add_argument("--workspace", default="runtime/workspace")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--max-steps", type=int, default=6)
    ARGS = ap.parse_args()

    try_load_model()
    srv = ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler)
    print(f"\n  🤖 Agiten 채팅 서버 실행 중")
    print(f"  브라우저에서 열기 →  http://localhost:{ARGS.port}\n")
    if not STATE["ready"]:
        print(f"  (아직 {STATE['detail']} — 학습이 끝나면 페이지에서 자동 인식돼요)\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n서버 종료")


if __name__ == "__main__":
    main()
