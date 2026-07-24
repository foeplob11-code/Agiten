"""합성 대화 생성기.

각 함수는 protocol.Message 리스트(한 대화)를 yield 한다.
표현은 banks.py 의 패러프레이즈 은행에서 뽑아 매번 다르게 만든다 →
같은 시나리오라도 문장이 겹치지 않아 다양성이 곱셈으로 늘어난다.
목표는 '언제 어떤 도구를 부르고, 확인은 언제 받는가'라는 에이전트 행동 각인.
"""

from __future__ import annotations

import random
from typing import Callable, Iterator

from ..protocol import Message, ToolCall
from ..toolspec import CONFIRM_REQUIRED
from . import banks as B

Dialog = list[Message]
Gen = Callable[[random.Random], Dialog]


def a(role, **kw):
    return Message(role=role, **kw)


def confirm_turn(r, action_desc: str) -> list[Message]:
    """어시스턴트가 확인을 구하고, 사용자가 승낙하는 2턴."""
    q = f"{action_desc} {B.pick(r, B.CONFIRM_Q)}"
    return [a("assistant",
              think=B.pick(r, ["되돌리기 어려운 작업이라 먼저 확인받는다.",
                               "실행 전에 사용자 동의를 받는다.",
                               "확인이 필요한 도구다. 내용을 밝히고 물어본다."]),
              content=q),
            a("user", content=B.pick(r, B.ACK))]


# ================================================================ 터미널

def gen_shell_simple(r):
    if B.maybe(r, 0.5):
        d = B.pick(r, B.DIRS)
        q = B.phrase(r, ["{d} 안에 뭐 있어?", "{d} 목록 보여줘", "{d} 뭐 들었는지 봐줘",
                         "{d} 파일 좀 보여줄래?"], d=d)
        tool, args = "fs.list", {"path": d}
        result = _fake(tool, args, r)
    else:
        q, cmd = B.pick(r, B.SHELL_CMDS)
        tool, args = "shell.run", {"cmd": cmd}
        result = _fake(tool, args, r)
    think = B.pick(r, [f"{tool} 로 확인하면 된다.", "바로 확인해보자."]) if B.maybe(r, 0.4) else ""
    return [
        a("user", content=q),
        a("assistant", think=think, calls=[ToolCall(tool, args)]),
        a("tool", content=result),
        a("assistant", content=_summ(result, r)),
    ]


def gen_shell_which(r):
    name = B.pick(r, ["docker", "node", "git", "ffmpeg", "psql", "brew", "code"])
    q = B.phrase(r, ["{n} 설치돼 있어?", "{n} 깔려있는지 확인해줘", "{n} 쓸 수 있어?"], n=name)
    return [
        a("user", content=q),
        a("assistant", calls=[ToolCall("shell.which", {"name": name})]),
        a("tool", content=f'{{"ok": true, "path": "/usr/local/bin/{name}"}}'),
        a("assistant", content=B.phrase(r, ["네, {n} 설치돼 있어요.", "{n} 있어요, 바로 쓰실 수 있어요."], n=name)),
    ]


def gen_shell_confirm(r):
    target = B.pick(r, ["node_modules", "__pycache__", "build", "*.log 파일들",
                        "dist", ".cache", "임시 파일들", "old_backup"])
    return [
        a("user", content=B.phrase(r, ["{t} 다 지워줘", "{t} 삭제해줘", "{t} 좀 정리해줘",
                                       "{t} 없애줘"], t=target)),
        *confirm_turn(r, f"`rm -rf {target}` 를 실행하려고 해요. 되돌릴 수 없는데"),
        a("assistant", calls=[ToolCall("shell.run", {"cmd": f"rm -rf {target}"})]),
        a("tool", content='{"ok": true, "exit_code": 0}'),
        a("assistant", content=B.phrase(r, ["{t} 정리했어요.", "{t} 삭제 완료했어요."], t=target)),
    ]


# ================================================================ 코드

def gen_code_fix(r):
    f = B.pick(r, B.FILES_PY)
    pkg = B.pick(r, B.PKGS)
    msg_t, diag_t, tool, argf = B.pick(r, B.ERRORS)
    msg = msg_t.format(pkg=pkg)
    diag = diag_t.format(pkg=pkg)
    args = argf(f=f, pkg=pkg)
    return [
        a("user", content=B.phrase(r, ["{f} 돌리니까 이런 에러 나: {m}",
                                       "{f} 실행하면 {m} 떠. 왜 그래?",
                                       "이 에러 좀 고쳐줘: {m}"], f=f, m=msg)),
        a("assistant", think=f"에러 원인 파악에 {tool} 이 필요하다.",
          content=diag, calls=[ToolCall(tool, args)]),
        a("tool", content=_fake(tool, args, r)),
        a("assistant", content=B.pick(r, ["해결했어요. 다시 실행해 보세요.",
                                          "고쳤어요. 이제 될 거예요.",
                                          "원인 잡았어요. 다시 돌려보세요."])),
    ]


def gen_code_write(r):
    desc, fname, code = B.pick(r, [
        ("CSV 읽어서 평균 내는 스크립트", "avg.py",
         "import csv\n\nwith open('data.csv') as f:\n"
         "    rows = list(csv.DictReader(f))\n"
         "vals = [float(x['value']) for x in rows]\n"
         "print(sum(vals) / len(vals))\n"),
        ("현재 시간 찍는 헬퍼", "clock.py",
         "from datetime import datetime\n\ndef now():\n    return datetime.now().isoformat()\n"),
        ("JSON 파일 예쁘게 포맷하는 스크립트", "prettyjson.py",
         "import json, sys\n\nwith open(sys.argv[1]) as f:\n    data = json.load(f)\n"
         "print(json.dumps(data, indent=2, ensure_ascii=False))\n"),
        ("폴더 안 파일 개수 세는 스크립트", "count.py",
         "import os, sys\n\nprint(len(os.listdir(sys.argv[1])))\n"),
    ])
    return [
        a("user", content=B.phrase(r, ["{d} 하나 만들어줘", "{d} 짜줘", "{d} 작성해줘"], d=desc)),
        a("assistant",
          think="파일 새로 쓰기는 확인이 필요. 내용을 먼저 보여주고 동의를 받는다.",
          content=f"`{fname}` 에 이렇게 쓸게요:\n```python\n{code}```\n" + B.pick(r, B.CONFIRM_Q)),
        a("user", content=B.pick(r, B.ACK)),
        a("assistant", calls=[ToolCall("fs.write", {"path": fname, "content": code})]),
        a("tool", content=f'{{"ok": true, "path": "{fname}", "bytes": {len(code)}}}'),
        a("assistant", content=B.phrase(r, ["`{f}` 저장했어요.", "`{f}` 만들어 뒀어요."], f=fname)),
    ]


def gen_code_edit(r):
    f = B.pick(r, B.FILES_PY)
    old, new = B.pick(r, [("localhost", "0.0.0.0"), ("debug=True", "debug=False"),
                          ("port=8000", "port=8080"), ("timeout=5", "timeout=30")])
    return [
        a("user", content=B.phrase(r, ["{f} 에서 {o} 를 {n} 으로 바꿔줘",
                                       "{f} 의 {o} 좀 {n} 로 고쳐줘"], f=f, o=old, n=new)),
        a("assistant", calls=[ToolCall("fs.edit", {"path": f, "old": old, "new": new})]),
        a("tool", content='{"ok": true, "replaced": 1}'),
        a("assistant", content=B.phrase(r, ["{f} 에서 {o} → {n} 바꿨어요.",
                                            "고쳤어요. {o} 를 {n} 로 변경했어요."], f=f, o=old, n=new)),
    ]


def gen_code_search(r):
    sym = B.pick(r, B.SYMBOLS)
    hit = B.pick(r, B.FILES_PY)
    return [
        a("user", content=B.phrase(r, ["`{s}` 어디서 쓰는지 찾아줘", "`{s}` 검색해줘",
                                       "`{s}` 정의된 데가 어디야?"], s=sym)),
        a("assistant", calls=[ToolCall("fs.search", {"pattern": sym})]),
        a("tool", content=f'{{"ok": true, "matches": [{{"path": "{hit}", "line": {r.randint(3, 90)}}}]}}'),
        a("assistant", content=B.phrase(r, ["`{h}` 에 있어요.", "`{h}` 파일에서 쓰고 있어요."], h=hit)),
    ]


def gen_code_tests(r):
    f = B.pick(r, B.FILES_PY)
    passed = r.randint(5, 30)
    failed = r.choice([0, 0, 1, 2])
    if failed == 0:
        return [
            a("user", content=B.pick(r, ["테스트 돌려줘", "테스트 통과하는지 봐줘", "pytest 실행해줘"])),
            a("assistant", calls=[ToolCall("code.run_tests", {"path": "tests/"})]),
            a("tool", content=f'{{"ok": true, "passed": {passed}, "failed": 0}}'),
            a("assistant", content=f"{passed}개 전부 통과했어요. 깨끗해요."),
        ]
    return [
        a("user", content=B.pick(r, ["테스트 돌려줘", "테스트 상태 확인해줘"])),
        a("assistant", think="먼저 테스트를 돌리고 결과를 본다.",
          calls=[ToolCall("code.run_tests", {"path": "tests/"})]),
        a("tool", content=f'{{"ok": true, "passed": {passed}, "failed": {failed}, "first_fail": "{f}::test_edge"}}'),
        a("assistant", think=f"{failed}건 실패. 해당 파일을 열어 원인을 본다.",
          calls=[ToolCall("fs.read", {"path": f})]),
        a("tool", content=f'{{"ok": true, "path": "{f}", "lines": {r.randint(20, 120)}}}'),
        a("assistant", content=f"{passed}개 통과, {failed}개 실패예요. `{f}::test_edge` 에서 "
                               f"경계값 처리가 빠진 것 같아요. 고쳐볼까요?"),
    ]


# ================================================================ 이메일

def gen_email_triage(r):
    p = B.pick(r, B.PEOPLE)
    topic = B.pick(r, B.TOPICS)
    n = r.randint(1, 4)
    return [
        a("user", content=B.pick(r, ["안 읽은 메일 요약해줘", "새 메일 있어?",
                                     "메일함 확인해줘", "오늘 온 메일 정리해줘"])),
        a("assistant", calls=[ToolCall("email.search", {"query": "is:unread", "limit": "10"})]),
        a("tool", content=f'{{"ok": true, "count": {n}, "items": [{{"id": "m1", "from": "{p}", "subject": "{topic}"}}]}}'),
        a("assistant", content=f"안 읽은 메일 {n}건 있어요. 가장 최근 건 {p} 님의 '{topic}' 메일이에요. "
                               + B.pick(r, ["열어볼까요?", "본문 볼까요?", "자세히 볼까요?"])),
    ]


def gen_email_read(r):
    p = B.pick(r, B.PEOPLE)
    topic = B.pick(r, B.TOPICS)
    return [
        a("user", content=B.phrase(r, ["{p} 이 보낸 메일 열어줘", "{p} 메일 읽어줘"], p=p)),
        a("assistant", calls=[ToolCall("email.read", {"id": "m1"})]),
        a("tool", content=f'{{"ok": true, "from": "{p}", "subject": "{topic}", '
                          f'"body": "{topic} 관련해서 내일까지 확인 부탁드립니다."}}'),
        a("assistant", content=f"{p} 님이 '{topic}' 관련해서 내일까지 확인해달라고 하네요. "
                               + B.pick(r, ["답장 써드릴까요?", "회신할까요?"])),
    ]


def gen_email_reply(r):
    p = B.pick(r, B.PEOPLE)
    topic = B.pick(r, B.TOPICS)
    body = f"{p}님, 안녕하세요.\n{topic} 관련해서 확인했고, 내일 오전까지 회신드리겠습니다.\n감사합니다."
    return [
        a("user", content=B.phrase(r, ["{p} 한테 {t} 답장 좀 써줘", "{p} 에게 {t} 회신 작성해줘"], p=p, t=topic)),
        a("assistant", think="초안은 자유롭게, 발송은 확인이 필요.",
          calls=[ToolCall("email.draft", {"to": p, "subject": f"RE: {topic}", "body": body})]),
        a("tool", content='{"ok": true, "draft_id": "d42"}'),
        a("assistant", content=f"초안 작성했어요:\n\n---\n{body}\n---\n\n" + B.pick(r, ["이대로 보낼까요?", "발송할까요?"])),
        a("user", content=B.pick(r, B.ACK)),
        a("assistant", calls=[ToolCall("email.send", {"draft_id": "d42"})]),
        a("tool", content='{"ok": true, "sent": true}'),
        a("assistant", content=B.pick(r, ["발송했어요.", "보냈어요.", "메일 전송 완료했어요."])),
    ]


# ================================================================ 메신저

def gen_chat_unread(r):
    p = B.pick(r, B.PEOPLE)
    ch = B.pick(r, B.CHANNELS)
    return [
        a("user", content=B.pick(r, ["안 읽은 메시지 있어?", "새 메시지 확인해줘", "읽지 않은 거 정리해줘"])),
        a("assistant", calls=[ToolCall("chat.unread", {})]),
        a("tool", content=f'{{"ok": true, "unread": [{{"channel": "{ch}", "from": "{p}", "n": {r.randint(1,5)}}}]}}'),
        a("assistant", content=f"{ch} 에 {p} 님 메시지가 와 있어요. 열어볼까요?"),
    ]


def gen_chat_relay(r):
    ch = B.pick(r, B.CHANNELS)
    p = B.pick(r, B.PEOPLE)
    text = B.pick(r, ["오늘 회의 3시로 미뤄졌대요", "PR 리뷰 부탁해요", "저녁에 시간 돼?",
                      "자료 언제까지 되나요?", "내일 반차 씁니다", "점심 같이 하실래요?"])
    return [
        a("user", content=B.phrase(r, ["{c} 안 읽은 거 있어?", "{c} 뭐 왔어?", "{c} 확인해줘"], c=ch)),
        a("assistant", calls=[ToolCall("chat.read", {"channel": ch, "limit": "10"})]),
        a("tool", content=f'{{"ok": true, "messages": [{{"from": "{p}", "text": "{text}"}}]}}'),
        a("assistant", content=f"{p} 님이 \"{text}\" 라고 남겼어요."),
    ]


def gen_chat_send(r):
    ch = B.pick(r, B.CHANNELS)
    text = B.pick(r, ["10분 뒤에 들어갈게요", "확인했습니다", "오늘은 재택합니다",
                      "조금 늦어요 먼저 시작하세요", "자료 방금 공유드렸어요", "네 좋습니다"])
    return [
        a("user", content=B.phrase(r, ["{c} 에 '{t}' 라고 보내줘", "{c} 에 {t} 전해줘",
                                       "{c} 한테 '{t}' 라고 남겨줘"], c=ch, t=text)),
        *confirm_turn(r, f"{ch} 에 \"{text}\" 보낼게요."),
        a("assistant", calls=[ToolCall("chat.send", {"channel": ch, "text": text})]),
        a("tool", content='{"ok": true, "sent": true}'),
        a("assistant", content=B.pick(r, ["보냈어요.", "전송했어요.", "전달했어요."])),
    ]


# ================================================================ 일정 / 기억

def gen_cal_list(r):
    n = r.randint(0, 3)
    if n == 0:
        return [
            a("user", content=B.pick(r, ["오늘 일정 뭐 있어?", "내 스케줄 보여줘", "오늘 약속 있나?"])),
            a("assistant", calls=[ToolCall("cal.list", {"date_from": "2026-07-24", "date_to": "2026-07-24"})]),
            a("tool", content='{"ok": true, "events": []}'),
            a("assistant", content="오늘은 잡힌 일정이 없어요. 여유로우시네요."),
        ]
    p = B.pick(r, B.PEOPLE)
    h = r.randint(9, 18)
    return [
        a("user", content=B.pick(r, ["오늘 일정 알려줘", "내일 뭐 있어?", "이번 주 일정 보여줘"])),
        a("assistant", calls=[ToolCall("cal.list", {"date_from": "2026-07-24", "date_to": "2026-07-24"})]),
        a("tool", content=f'{{"ok": true, "events": [{{"title": "{p} 미팅", "start": "{h}:00"}}]}}'),
        a("assistant", content=f"{h}시에 {p} 님과 미팅이 있어요."),
    ]


def gen_cal_create(r):
    p = B.pick(r, B.PEOPLE)
    h = r.randint(9, 18)
    return [
        a("user", content=B.phrase(r, ["내일 {h}시에 {p} 랑 미팅 잡아줘",
                                       "{p} 랑 내일 {h}시 회의 등록해줘",
                                       "내일 {h}시 {p} 미팅 추가해줘"], h=h, p=p)),
        *confirm_turn(r, f"내일 {h}:00~{h+1}:00 '{p} 미팅' 으로 등록할게요."),
        a("assistant", calls=[ToolCall("cal.create",
                                       {"title": f"{p} 미팅",
                                        "start": f"2026-07-25T{h:02d}:00:00",
                                        "end": f"2026-07-25T{h+1:02d}:00:00",
                                        "attendees": p})]),
        a("tool", content='{"ok": true, "event_id": "ev7"}'),
        a("assistant", content=B.pick(r, ["일정 등록했어요.", "캘린더에 넣었어요.", "추가해 뒀어요."])),
    ]


def gen_memory_save(r):
    q, key, val = B.pick(r, [
        ("나 커피 안 마셔 기억해둬", "선호", "커피 안 마심"),
        ("내 깃허브 아이디는 hobak 이야", "github_id", "hobak"),
        ("배포는 항상 금요일 피해줘", "규칙", "금요일 배포 금지"),
        ("나 매운 거 못 먹어", "선호", "매운 음식 못 먹음"),
        ("회의는 오전에 잡아줘", "규칙", "회의는 오전 선호"),
        ("내 자리는 3층 창가야", "정보", "자리: 3층 창가"),
    ])
    return [
        a("user", content=q),
        a("assistant", calls=[ToolCall("memory.save", {"key": key, "value": val})]),
        a("tool", content='{"ok": true}'),
        a("assistant", content=B.pick(r, ["기억해 뒀어요.", "메모했어요.", "저장했어요. 다음에 반영할게요."])),
    ]


def gen_memory_recall(r):
    q, ans = B.pick(r, [
        ("내 깃허브 아이디 뭐였지?", "hobak 이에요."),
        ("나 커피 마셨나?", "커피는 안 드시는 걸로 기억하고 있어요."),
        ("배포 관련해서 내가 뭐라고 했었지?", "금요일에는 배포하지 말라고 하셨어요."),
    ])
    return [
        a("user", content=q),
        a("assistant", calls=[ToolCall("memory.recall", {"query": q})]),
        a("tool", content=f'{{"ok": true, "hit": "{ans}"}}'),
        a("assistant", content=ans),
    ]


# ================================================================ 웹

def gen_web_search(r):
    topic = B.pick(r, ["파이썬 3.13 새 기능", "서울 내일 날씨", "도커 컴포즈 문법",
                       "환율 원달러", "리액트 19 변경점", "깃 리베이스 방법"])
    return [
        a("user", content=B.phrase(r, ["{t} 검색해줘", "{t} 좀 찾아줘", "{t} 알아봐줘"], t=topic)),
        a("assistant", calls=[ToolCall("web.search", {"query": topic})]),
        a("tool", content=f'{{"ok": true, "results": [{{"title": "{topic} 정리", "url": "https://ex.com/a"}}]}}'),
        a("assistant", content=f"'{topic}' 관련 자료 찾았어요. 요약해 드릴까요, 링크 열어드릴까요?"),
    ]


def gen_web_fetch(r):
    return [
        a("user", content=B.pick(r, ["이 링크 요약해줘 https://ex.com/article",
                                     "https://ex.com/doc 내용 정리해줘"])),
        a("assistant", calls=[ToolCall("web.fetch", {"url": "https://ex.com/article"})]),
        a("tool", content='{"ok": true, "title": "요약 대상 글", "text": "본문 내용..."}'),
        a("assistant", content="핵심만 정리하면, 이 글은 세 가지 요점을 다루고 있어요. 자세히 풀어드릴까요?"),
    ]


# ================================================================ 다중 도구 / 거절 / 잡담

def gen_multi_deploy(r):
    """상태 확인 → 테스트 → 배포 확인, 실전형 다중 스텝."""
    return [
        a("user", content=B.pick(r, ["배포해도 되는 상태인지 봐줘", "지금 배포 가능한지 확인해줘"])),
        a("assistant", think="먼저 변경사항과 테스트 상태를 확인한다.",
          calls=[ToolCall("shell.run", {"cmd": "git status --short"})]),
        a("tool", content='{"ok": true, "stdout": "M app.py"}'),
        a("assistant", think="변경 있음. 테스트부터 돌린다.",
          calls=[ToolCall("code.run_tests", {"path": "tests/"})]),
        a("tool", content='{"ok": true, "passed": 18, "failed": 0}'),
        a("assistant", content="변경된 파일 1개 있고 테스트 18개 전부 통과예요. 배포 진행할까요?"),
    ]


def gen_refuse(r):
    q, why = B.pick(r, [
        ("내 계좌에서 10만원 이체해줘", "금융 이체는 제가 대신 실행할 수 없어요"),
        ("이 사이트 캡차 좀 풀어줘", "캡차(봇 감지)는 제가 대신 처리하면 안 되는 부분이에요"),
        ("내 비밀번호 입력해서 로그인해줘", "비밀번호 입력은 제가 대신 하면 안 돼요"),
        ("내 카드번호로 결제 진행해줘", "카드 정보 입력·결제는 직접 하셔야 해요"),
    ])
    return [
        a("user", content=q),
        a("assistant",
          think="금융/캡차/비밀번호 등은 대신 실행하면 안 되는 작업이다. 정직하게 한계를 말한다.",
          content=f"{why}. 직접 진행하셔야 하는 부분이라, 대신 필요한 정보나 절차를 정리해 드릴게요."),
    ]


def gen_chitchat(r):
    q, ans = B.pick(r, B.GREETINGS)
    return [a("user", content=q), a("assistant", content=ans)]


# ================================================================ 새 시나리오

def gen_git(r):
    q, cmd, need_confirm = B.pick(r, B.GIT_TASKS)
    if need_confirm:
        return [
            a("user", content=q),
            *confirm_turn(r, f"`{cmd}` 실행할게요."),
            a("assistant", calls=[ToolCall("shell.run", {"cmd": cmd})]),
            a("tool", content='{"ok": true, "exit_code": 0}'),
            a("assistant", content=B.pick(r, B.DONE)),
        ]
    return [
        a("user", content=q),
        a("assistant", calls=[ToolCall("shell.run", {"cmd": cmd})]),
        a("tool", content=_fake("shell.run", {"cmd": cmd}, r)),
        a("assistant", content=B.pick(r, ["확인했어요, 위 내용이에요.", "결과 보여드렸어요.",
                                          "이렇게 나와요."])),
    ]


def gen_log_analysis(r):
    """로그를 읽어 에러를 찾는 2-스텝."""
    logf = B.pick(r, ["/var/log/app.log", "./logs/error.log", "server.log", "./logs/train.log"])
    err = B.pick(r, ["ConnectionTimeout", "OOMError", "500 Internal Error",
                     "PermissionDenied", "NullPointer"])
    return [
        a("user", content=B.phrase(r, ["{f} 에서 에러 있나 봐줘", "{f} 최근 에러 찾아줘",
                                       "{f} 뭐 문제 있어?"], f=logf)),
        a("assistant", think="로그 마지막 부분을 읽어 에러를 찾는다.",
          calls=[ToolCall("shell.run", {"cmd": f"tail -n 50 {logf}"})]),
        a("tool", content=f'{{"ok": true, "stdout": "... ERROR {err} at line 88 ..."}}'),
        a("assistant", content=f"`{err}` 에러가 보여요. 88번째 줄쯤에서 났어요. 원인 찾아볼까요?"),
    ]


def gen_reminder(r):
    when = B.pick(r, ["30분 뒤", "내일 아침 9시", "오후 3시", "퇴근 전", "다음 주 월요일"])
    what = B.pick(r, ["약 먹기", "회의 자료 보내기", "지훈한테 전화", "빨래 돌리기",
                      "보고서 제출", "택배 찾기", "은행 업무"])
    return [
        a("user", content=B.phrase(r, ["{w}에 {t} 알려줘", "{w} {t} 리마인드 해줘",
                                       "{w}에 {t} 잊지 않게 해줘"], w=when, t=what)),
        a("assistant", calls=[ToolCall("memory.save",
                                       {"key": f"리마인더:{when}", "value": what})]),
        a("tool", content='{"ok": true}'),
        a("assistant", content=f"{when}에 '{what}' 알려드릴게요. 기억해 뒀어요."),
    ]


def gen_file_organize(r):
    ext = B.pick(r, ["png", "pdf", "csv", "jpg", "zip", "mp4"])
    dst = B.pick(r, ["images", "docs", "backup", "정리함", "archive"])
    return [
        a("user", content=B.phrase(r, ["{e} 파일들 {d} 폴더로 옮겨줘",
                                       "{e} 전부 {d} 로 정리해줘"], e=ext, d=dst)),
        *confirm_turn(r, f"현재 폴더의 *.{ext} 파일들을 `{dst}/` 로 옮길게요."),
        a("assistant", calls=[ToolCall("shell.run",
                                       {"cmd": f"mkdir -p {dst} && mv *.{ext} {dst}/"})]),
        a("tool", content=f'{{"ok": true, "moved": {r.randint(2, 15)}}}'),
        a("assistant", content=f"{ext} 파일들 `{dst}/` 로 옮겼어요."),
    ]


def gen_clarify(r):
    """모호한 요청 → 함부로 실행하지 않고 되묻는다(중요 행동)."""
    vague, ask = B.pick(r, [
        ("파일 지워줘", "어떤 파일을 지울까요? 경로나 이름을 알려주세요."),
        ("메일 보내줘", "누구에게, 어떤 내용으로 보낼지 알려주시면 초안부터 만들게요."),
        ("그거 고쳐줘", "어떤 파일의 무엇을 고칠지 조금 더 알려주세요."),
        ("정리해줘", "어떤 걸 정리할까요? 파일, 메일, 일정 중 무엇인가요?"),
        ("실행해줘", "무엇을 실행할지 명령이나 파일을 알려주세요."),
        ("보내줘", "어디로 무엇을 보낼까요? 메일인지 메신저인지 알려주세요."),
    ])
    return [
        a("user", content=vague),
        a("assistant", think="정보가 부족하다. 함부로 실행하지 말고 되묻는다.", content=ask),
    ]


def gen_data_process(r):
    f = B.pick(r, ["data.csv", "sales.csv", "users.csv", "log.csv", "결과.csv"])
    op = B.pick(r, [("행이 몇 개야?", "wc -l"), ("컬럼 이름 보여줘", "head -1"),
                    ("첫 5줄 보여줘", "head -5")])
    q, cmd = op
    return [
        a("user", content=f"{f} {q}"),
        a("assistant", calls=[ToolCall("shell.run", {"cmd": f"{cmd} {f}"})]),
        a("tool", content=f'{{"ok": true, "stdout": "{r.randint(10, 9999)}"}}' if cmd == "wc -l"
          else '{"ok": true, "stdout": "id,name,value"}'),
        a("assistant", content=B.pick(r, ["확인했어요, 위와 같아요.", "이렇게 나와요."])),
    ]


# ---------------------------------------------------------------- 멀티턴 래퍼

FOLLOWUPS = [
    ("고마워", None),
    ("방금 거 다시 보여줘", None),
    ("그럼 그다음은?", None),
    ("하나만 더 해줘", None),
    ("알겠어 수고", None),
]


def add_followup(r, dialog):
    """일부 대화 끝에 짧은 후속 턴을 붙여 맥락 대화를 학습시킨다."""
    q, _ = B.pick(r, FOLLOWUPS)
    ans = B.pick(r, ["네, 또 필요하면 말씀하세요.", "알겠어요. 바로 해드릴게요.",
                     "넵, 방금 결과 다시 정리해 드릴게요.", "언제든 불러주세요."])
    return dialog + [a("user", content=q), a("assistant", content=ans)]


# ================================================================ 가짜 결과

def _fake(tool, args, r):
    if tool == "fs.list":
        n = r.randint(2, 6)
        names = r.sample(B.FILES_PY + B.FILES_OTHER + ["data/", ".git/", "src/"], min(n, 8))
        return f'{{"ok": true, "entries": {names}}}'.replace("'", '"')
    if tool == "shell.which":
        return f'{{"ok": true, "path": "/usr/bin/{args.get("name", "x")}"}}'
    if tool == "fs.read":
        return f'{{"ok": true, "path": "{args.get("path")}", "lines": {r.randint(10, 120)}}}'
    cmd = args.get("cmd", "")
    table = {
        "df -h": '{"ok": true, "stdout": "/dev/disk1  460G  300G  160G"}',
        "free -h": '{"ok": true, "stdout": "Mem: 16G used 9G free 7G"}',
        "git branch --show-current": '{"ok": true, "stdout": "main"}',
        "git status --short": '{"ok": true, "stdout": "M app.py"}',
        "git log -1 --oneline": '{"ok": true, "stdout": "a1b2c3d fix: null 체크 추가"}',
        "pgrep -fl python": '{"ok": true, "stdout": "8123 python train.py"}',
        "lsof -i :8000": '{"ok": true, "stdout": "python 8123 ... TCP *:8000 (LISTEN)"}',
        "python --version": '{"ok": true, "stdout": "Python 3.11.6"}',
        "du -sh .": '{"ok": true, "stdout": "1.2G ."}',
        "ping -c 1 8.8.8.8": '{"ok": true, "stdout": "1 packets received"}',
        "date": '{"ok": true, "stdout": "2026-07-24 14:30 KST"}',
        "nproc": '{"ok": true, "stdout": "8"}',
        "docker ps": '{"ok": true, "stdout": "web  Up 2 hours  0.0.0.0:80->80"}',
        "whoami": '{"ok": true, "stdout": "hobak"}',
        "echo $PATH": '{"ok": true, "stdout": "/usr/local/bin:/usr/bin:/bin"}',
        "git diff": '{"ok": true, "stdout": "@@ -1,3 +1,4 @@ ..."}',
        "git push": '{"ok": true, "stdout": "main -> main"}',
        "git stash": '{"ok": true, "stdout": "Saved working directory"}',
        "git checkout main": '{"ok": true, "stdout": "Switched to branch main"}',
        "git checkout -b feature": '{"ok": true, "stdout": "Switched to a new branch feature"}',
        "git log -5 --oneline": '{"ok": true, "stdout": "a1b2c3d fix\\ne4f5g6h feat"}',
        "pip list": '{"ok": true, "stdout": "numpy 1.26\\nrequests 2.31"}',
    }
    if cmd in table:
        return table[cmd]
    if "pip install" in cmd:
        return '{"ok": true, "stdout": "Successfully installed"}'
    return '{"ok": true, "exit_code": 0}'


def _summ(result, r):
    if "160G" in result:
        return B.pick(r, ["160GB 정도 남았어요.", "여유 공간 160GB 예요."])
    if '"main"' in result:
        return "지금 `main` 브랜치예요."
    if "8123 python train" in result:
        return "네, `train.py` 가 PID 8123 으로 돌고 있어요."
    if "M app.py" in result:
        return "`app.py` 가 수정된 상태예요."
    if "fix: null" in result:
        return "가장 최근 커밋은 'null 체크 추가' 예요."
    if "Python 3.11" in result:
        return "파이썬 3.11.6 이에요."
    if "1.2G" in result:
        return "이 폴더는 1.2GB 정도예요."
    if "packets received" in result:
        return "네트워크 정상이에요."
    if "LISTEN" in result:
        return "8000 포트는 `train.py`(PID 8123)가 쓰고 있어요."
    if "16G used" in result:
        return "메모리 7GB 정도 여유 있어요."
    if "Successfully installed" in result:
        return "설치 완료했어요."
    if "entries" in result:
        return B.pick(r, ["목록 확인했어요. 위 파일들이에요.", "이 파일들이 들어 있어요."])
    return B.pick(r, ["확인했어요.", "봤어요."])


# ---------------------------------------------------------------- 레지스트리

GENERATORS: list[tuple[Gen, float]] = [
    (gen_shell_simple, 1.4),
    (gen_shell_which, 0.5),
    (gen_shell_confirm, 0.8),
    (gen_code_fix, 1.1),
    (gen_code_write, 1.1),
    (gen_code_edit, 0.8),
    (gen_code_search, 0.8),
    (gen_code_tests, 0.9),
    (gen_email_triage, 0.8),
    (gen_email_read, 0.6),
    (gen_email_reply, 1.0),
    (gen_chat_unread, 0.6),
    (gen_chat_relay, 0.8),
    (gen_chat_send, 0.8),
    (gen_cal_list, 0.7),
    (gen_cal_create, 0.8),
    (gen_memory_save, 0.6),
    (gen_memory_recall, 0.5),
    (gen_web_search, 0.6),
    (gen_web_fetch, 0.4),
    (gen_multi_deploy, 0.9),
    (gen_refuse, 0.6),
    (gen_chitchat, 0.7),
    # 새 시나리오
    (gen_git, 1.0),
    (gen_log_analysis, 0.7),
    (gen_reminder, 0.7),
    (gen_file_organize, 0.7),
    (gen_clarify, 0.8),
    (gen_data_process, 0.6),
]


def sample_dialog(r):
    gens, weights = zip(*GENERATORS)
    dialog = r.choices(gens, weights=weights, k=1)[0](r)
    # 20% 대화에 후속 턴을 붙여 맥락 대화를 학습(되묻기·인사 등 짧은 대화는 제외)
    if len(dialog) >= 4 and B.maybe(r, 0.2):
        dialog = add_followup(r, dialog)
    return dialog


def iter_dialogs(n: int, seed: int = 0) -> Iterator[Dialog]:
    r = random.Random(seed)
    for _ in range(n):
        yield sample_dialog(r)
