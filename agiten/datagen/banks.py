"""슬롯 값 은행 + 패러프레이즈 유틸.

데이터 다양성의 원천. 여기 값을 늘리면 생성되는 대화의 표현 다양성이
곱셈으로 증가한다. 문장은 고정하지 말고 항상 여러 표현을 두고 뽑는다.
"""

from __future__ import annotations

import random

# ================================================================ 슬롯 은행

FILES_PY = [
    "main.py", "app.py", "utils.py", "train.py", "server.py", "parser.py",
    "models/user.py", "src/config.py", "tests/test_api.py", "handlers.py",
    "db.py", "auth.py", "pipeline.py", "scheduler.py", "cli.py", "routes.py",
]
FILES_OTHER = [
    "README.md", "config.yaml", "package.json", "index.html", "style.css",
    "Dockerfile", ".env", "requirements.txt", "app.js", "schema.sql",
    "notes.txt", "report.md", "data.csv", "settings.json",
]
DIRS = [
    "~/project", "~/work/agiten", "./src", "/var/log", "~/Downloads",
    "./data", "~/Desktop", "/tmp", "./build", "~/repos/web", "./tests",
    "~/문서", "./logs", "/etc/nginx",
]
PEOPLE = [
    "지훈", "수민", "김대리", "박팀장", "Alex", "Sarah", "엄마", "민재",
    "은지", "최과장", "David", "정우", "하윤", "이사님", "지원", "Mike",
]
CHANNELS = [
    "#general", "#dev", "#랜덤", "팀 채팅방", "가족방", "@지훈", "#backend",
    "#공지", "프로젝트방", "@수민", "#design", "동아리방", "#alert",
]
TOPICS = [
    "배포 일정", "회의 자료", "코드 리뷰", "점심 약속", "버그 리포트",
    "주간 보고", "휴가 신청", "예산 검토", "디자인 시안", "채용 면접",
    "계약서 검토", "출장 일정", "장애 대응", "신규 기능 제안",
]
PKGS = [
    "requests", "numpy", "pandas", "fastapi", "torch", "flask", "pytest",
    "django", "aiohttp", "pydantic", "scikit-learn", "matplotlib", "redis",
]
SYMBOLS = [
    "load_config", "API_KEY", "def train", "TODO", "class User", "get_db",
    "SECRET", "async def", "import torch", "@app.route", "DATABASE_URL",
    "def main", "class Model", "FIXME", "handle_request",
]
SHELL_CMDS = [
    ("지금 디스크 용량 얼마나 남았어?", "df -h"),
    ("실행 중인 파이썬 프로세스 있어?", "pgrep -fl python"),
    ("현재 깃 브랜치 뭐야?", "git branch --show-current"),
    ("바뀐 파일 있는지 봐줘", "git status --short"),
    ("메모리 얼마나 쓰고 있어?", "free -h"),
    ("포트 8000 누가 쓰고 있어?", "lsof -i :8000"),
    ("가장 최근 커밋 뭐야?", "git log -1 --oneline"),
    ("현재 폴더 용량 알려줘", "du -sh ."),
    ("파이썬 버전 확인해줘", "python --version"),
    ("네트워크 연결됐는지 확인해줘", "ping -c 1 8.8.8.8"),
]
ERRORS = [
    ("ModuleNotFoundError: No module named '{pkg}'",
     "{pkg} 모듈이 설치 안 돼 있어서 나는 에러예요.",
     "shell.run", lambda pkg, **k: {"cmd": f"pip install {pkg}"}),
    ("IndentationError: unexpected indent",
     "들여쓰기가 어긋난 줄이 있어요.",
     "fs.read", lambda f, **k: {"path": f}),
    ("TypeError: 'NoneType' object is not subscriptable",
     "None 을 인덱싱해서 나는 에러예요. 값이 비어있는 경우를 확인해야 해요.",
     "fs.read", lambda f, **k: {"path": f}),
    ("SyntaxError: invalid syntax",
     "문법 오류가 있어요. 해당 줄을 열어볼게요.",
     "fs.read", lambda f, **k: {"path": f}),
    ("ConnectionRefusedError: [Errno 61] Connection refused",
     "서버가 안 떠 있는 것 같아요. 프로세스를 확인할게요.",
     "shell.run", lambda **k: {"cmd": "pgrep -fl server"}),
]

# ================================================================ 패러프레이즈 은행
# {slot} 자리표시자를 쓰고, phrase() 로 채운다.

# 사용자 승낙
ACK = ["응", "그래", "ㅇㅇ", "ㅇㅋ", "좋아", "진행해", "해줘", "그렇게 해",
       "응 부탁해", "맞아 진행", "오케이", "고고", "네 해주세요", "ㄱㄱ"]

# 사용자 거절/보류
NACK = ["아니 잠깐", "아직 하지마", "취소", "다시 생각해볼게", "아니야 됐어"]

# 어시스턴트 확인 질문 (되돌릴 수 없는 작업 전)
CONFIRM_Q = [
    "진행할까요?", "이대로 할까요?", "실행해도 될까요?", "괜찮으세요?",
    "맞나요?", "이렇게 할게요, 진행해도 되죠?", "확인 한 번만 부탁드려요.",
    "지금 실행할까요?",
]

# 완료 알림
DONE = ["완료했어요.", "처리했어요.", "됐어요.", "끝났어요.", "마쳤어요.",
        "적용했어요.", "반영했어요."]

# 인사/잡담
GREETINGS = [
    ("안녕", "안녕하세요! 오늘 뭐 도와드릴까요?"),
    ("하이", "네, 안녕하세요. 무엇을 도와드릴까요?"),
    ("잘 지냈어?", "저야 늘 준비돼 있죠. 오늘은 어떤 일부터 볼까요?"),
    ("고마워", "천만에요. 또 필요하면 불러주세요."),
    ("수고했어", "감사해요. 남은 것도 편하게 맡겨주세요."),
    ("피곤하다", "고생 많으셨어요. 제가 덜어드릴 일이 있을까요?"),
    ("바쁘다", "그럼 우선순위 높은 것부터 처리할게요. 뭐가 급하세요?"),
    ("넌 뭘 할 수 있어?",
     "터미널, 파일·코드 편집, 이메일, 메신저, 일정 관리를 도와드려요. 필요한 걸 말씀해 주세요."),
    ("뭐 하고 있어?", "대기 중이에요. 시키실 일 있으면 바로 시작할게요."),
]


def pick(r: random.Random, seq):
    return r.choice(seq)


def phrase(r: random.Random, templates: list[str], **slots) -> str:
    """여러 표현 중 하나를 골라 슬롯을 채운다."""
    return r.choice(templates).format(**slots)


def maybe(r: random.Random, p: float = 0.5) -> bool:
    return r.random() < p
