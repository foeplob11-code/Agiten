"""Agiten 도구 카탈로그.

데이터 생성과 런타임이 **같은 정의**를 본다.
여기에 도구를 추가하면 학습 데이터와 실행기 양쪽에 동시에 반영된다.
`confirm=True` 인 도구는 되돌리기 어려운 작업 → 실행 전 사용자 확인이 필요하다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolSpec:
    name: str
    desc: str
    args: dict[str, str] = field(default_factory=dict)
    confirm: bool = False


CATALOG: list[ToolSpec] = [
    # ------------------------------------------------------------ 터미널
    ToolSpec("shell.run", "셸 명령 실행",
             {"cmd": "실행할 명령", "cwd": "작업 디렉토리(선택)"}),
    ToolSpec("shell.which", "명령/실행파일 존재 확인", {"name": "명령 이름"}),

    # ------------------------------------------------------------ 파일 / 코드
    ToolSpec("fs.list", "디렉토리 목록", {"path": "경로"}),
    ToolSpec("fs.read", "파일 읽기",
             {"path": "경로", "start": "시작 줄(선택)", "end": "끝 줄(선택)"}),
    ToolSpec("fs.write", "파일 새로 쓰기(덮어씀)",
             {"path": "경로", "content": "내용"}, confirm=True),
    ToolSpec("fs.edit", "파일 부분 치환",
             {"path": "경로", "old": "찾을 문자열", "new": "바꿀 문자열"}),
    ToolSpec("fs.search", "코드/텍스트 검색",
             {"pattern": "정규식", "path": "검색 범위(선택)"}),
    ToolSpec("code.run_tests", "테스트 실행", {"path": "대상 경로(선택)"}),

    # ------------------------------------------------------------ 이메일
    ToolSpec("email.search", "메일 검색",
             {"query": "검색어", "limit": "개수(선택)"}),
    ToolSpec("email.read", "메일 본문 읽기", {"id": "메일 ID"}),
    ToolSpec("email.draft", "메일 초안 작성",
             {"to": "받는 사람", "subject": "제목", "body": "본문"}),
    ToolSpec("email.send", "초안 발송",
             {"draft_id": "초안 ID"}, confirm=True),

    # ------------------------------------------------------------ 메신저
    ToolSpec("chat.unread", "안 읽은 메시지 목록", {}),
    ToolSpec("chat.read", "대화방 메시지 읽기",
             {"channel": "대화방", "limit": "개수(선택)"}),
    ToolSpec("chat.send", "메시지 전송",
             {"channel": "대화방", "text": "내용"}, confirm=True),

    # ------------------------------------------------------------ 일정
    ToolSpec("cal.list", "일정 조회",
             {"date_from": "시작일 YYYY-MM-DD", "date_to": "종료일 YYYY-MM-DD"}),
    ToolSpec("cal.create", "일정 생성",
             {"title": "제목", "start": "시작 ISO", "end": "종료 ISO",
              "attendees": "참석자 목록(선택)"}, confirm=True),

    # ------------------------------------------------------------ 기억
    ToolSpec("memory.save", "장기 기억 저장", {"key": "키", "value": "값"}),
    ToolSpec("memory.recall", "장기 기억 검색", {"query": "검색어"}),

    # ------------------------------------------------------------ 웹
    ToolSpec("web.search", "웹 검색", {"query": "검색어"}),
    ToolSpec("web.fetch", "URL 본문 가져오기", {"url": "주소"}),
]

BY_NAME: dict[str, ToolSpec] = {t.name: t for t in CATALOG}

CONFIRM_REQUIRED: frozenset[str] = frozenset(t.name for t in CATALOG if t.confirm)


def render_catalog(tools: list[ToolSpec] | None = None) -> str:
    """시스템 프롬프트에 넣을 도구 목록 문자열.

    작은 모델이라 JSON 스키마 대신 한 줄 요약으로 토큰을 아낀다.
    """
    lines = []
    for t in tools or CATALOG:
        argstr = ", ".join(f"{k}: {v}" for k, v in t.args.items()) or "없음"
        mark = " [확인필요]" if t.confirm else ""
        lines.append(f"- {t.name}({argstr}){mark} — {t.desc}")
    return "\n".join(lines)
