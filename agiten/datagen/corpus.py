"""프리트레인/토크나이저용 순수 텍스트 코퍼스.

사전학습 가중치가 없으므로 '언어 자체'를 여기서 배워야 한다.
합성 템플릿만으로는 유창성·어휘에 한계가 있다 → 진짜 1.5B 를 노릴 땐
scripts/fetch_pretrain.py 로 공개 코퍼스를 붙이는 것을 전제로 한다.
이 파일은 부트스트랩/파이프라인 검증 + 어휘 시드용 텍스트를 만든다.
"""

from __future__ import annotations

import random
from itertools import product
from typing import Iterator

# ---------------------------------------------------------------- 자연어 조각

SUBJECTS = ["나는", "그는", "우리는", "사용자는", "개발자는", "비서는", "모델은",
            "그녀는", "팀은", "회사는", "학생은", "친구는", "그들은", "당신은"]
VERBS = ["확인했다", "저장했다", "실행했다", "요청했다", "정리했다", "보고했다",
         "검토했다", "수정했다", "전송했다", "취소했다", "분석했다", "설치했다",
         "삭제했다", "공유했다", "예약했다", "기록했다", "비교했다", "완료했다"]
OBJECTS = ["파일을", "메일을", "일정을", "코드를", "메시지를", "결과를", "로그를",
           "설정을", "문서를", "회의를", "예산을", "보고서를", "데이터를", "요청을"]
ADVS = ["곧바로", "조심스럽게", "다시", "천천히", "정확히", "우선", "결국", "미리",
        "꼼꼼히", "빠르게", "차분히", "먼저", "일단", "제대로"]

FACTS = [
    "터미널은 명령어로 컴퓨터를 다루는 도구다.",
    "파이썬은 들여쓰기로 코드 블록을 구분한다.",
    "이메일을 보내기 전에는 받는 사람과 제목을 확인하는 것이 좋다.",
    "되돌릴 수 없는 작업은 실행 전에 한 번 더 확인해야 한다.",
    "함수는 입력을 받아 출력을 돌려주는 코드 묶음이다.",
    "일정은 시작 시각과 종료 시각으로 표현한다.",
    "검색은 원하는 정보를 빠르게 찾는 방법이다.",
    "버전 관리는 코드의 변경 이력을 기록한다.",
    "테스트는 코드가 의도대로 동작하는지 확인한다.",
    "로그를 보면 프로그램이 어디서 멈췄는지 알 수 있다.",
    "변수는 값을 담아 두는 이름표다.",
    "반복문은 같은 작업을 여러 번 수행한다.",
    "조건문은 상황에 따라 다른 코드를 실행한다.",
    "리스트는 여러 값을 순서대로 담는 자료구조다.",
    "딕셔너리는 키와 값을 짝지어 저장한다.",
    "예외 처리는 오류가 나도 프로그램이 멈추지 않게 한다.",
    "커밋은 코드 변경을 하나의 단위로 기록하는 일이다.",
    "브랜치는 작업을 갈래로 나눠 병행하게 해준다.",
    "환경 변수는 프로그램 밖에서 설정값을 전달한다.",
    "패키지는 재사용 가능한 코드 묶음이다.",
    "회의는 참석자와 시간을 미리 정해 잡는다.",
    "메모는 나중에 기억하기 위해 짧게 적어 둔다.",
    "백업은 데이터를 잃지 않도록 복사해 두는 일이다.",
    "정렬은 값을 일정한 기준으로 순서대로 늘어놓는 것이다.",
]

CODE_SNIPPETS = [
    "def add(a, b):\n    return a + b\n",
    "for i in range(10):\n    print(i)\n",
    "import json\ndata = json.loads(text)\nprint(data['name'])\n",
    "with open('f.txt') as f:\n    lines = f.readlines()\n",
    "class Dog:\n    def __init__(self, name):\n        self.name = name\n",
    "try:\n    run()\nexcept Exception as e:\n    print(e)\n",
    "result = [x * 2 for x in nums if x > 0]\n",
    "async def fetch(url):\n    async with session.get(url) as r:\n        return await r.text()\n",
    "if __name__ == '__main__':\n    main()\n",
    "git commit -m 'fix: 경계값 처리 추가'\n",
    "df = pd.read_csv('data.csv')\nprint(df.head())\n",
    "@app.route('/health')\ndef health():\n    return {'ok': True}\n",
    "def factorial(n):\n    return 1 if n <= 1 else n * factorial(n - 1)\n",
    "os.makedirs(path, exist_ok=True)\n",
    "response = requests.get(url, timeout=10)\nresponse.raise_for_status()\n",
    "numbers = sorted(data, key=lambda x: x['score'], reverse=True)\n",
    "with open('out.json', 'w') as f:\n    json.dump(data, f, ensure_ascii=False)\n",
    "docker run -d -p 8000:8000 myapp:latest\n",
    "SELECT name, count(*) FROM users GROUP BY name;\n",
    "export PATH=$PATH:/usr/local/bin\n",
]

QA_PAIRS = [
    ("파이썬에서 리스트를 정렬하려면?", "sorted() 함수나 리스트의 sort() 메서드를 쓴다."),
    ("깃에서 마지막 커밋을 취소하려면?", "git reset --soft HEAD~1 로 되돌린다."),
    ("파일이 있는지 확인하려면?", "os.path.exists(경로) 로 확인한다."),
    ("메일을 예약 발송하려면?", "초안을 만든 뒤 원하는 시각에 발송을 예약한다."),
    ("현재 폴더 경로를 알려면?", "pwd 명령이나 os.getcwd() 를 쓴다."),
    ("문자열을 숫자로 바꾸려면?", "int() 나 float() 로 변환한다."),
    ("딕셔너리의 모든 키를 보려면?", "keys() 메서드를 쓴다."),
    ("실행 중인 프로세스를 멈추려면?", "kill 명령에 프로세스 번호를 준다."),
    ("깃 변경사항을 되돌리려면?", "git checkout -- 파일명 으로 되돌린다."),
    ("두 파일의 차이를 보려면?", "diff 명령이나 git diff 를 쓴다."),
]

# 지시-응답 스타일(에이전트 톤 시드)
INSTRUCT = [
    ("폴더 정리해줘", "어떤 폴더를 정리할지 알려주시면 바로 시작할게요."),
    ("회의 잡아줘", "누구와 언제 잡을지 알려주세요. 확인 후 등록하겠습니다."),
    ("메일 요약해줘", "메일함을 확인해서 안 읽은 것부터 정리해 드릴게요."),
    ("이거 배포해줘", "먼저 테스트 상태를 확인하고, 문제 없으면 확인받고 진행할게요."),
]


def _sentence(r: random.Random) -> str:
    return f"{r.choice(SUBJECTS)} {r.choice(ADVS)} {r.choice(OBJECTS)} {r.choice(VERBS)}."


def iter_corpus_lines(seed: int = 0, n_synth: int = 12000) -> Iterator[str]:
    r = random.Random(seed)

    # 사실 문장 (반복 노출로 상식·어휘 각인)
    for fact in FACTS:
        for _ in range(15):
            yield fact

    # 코드 스니펫
    for code in CODE_SNIPPETS:
        for _ in range(15):
            yield code

    # QA / 지시
    for q, ans in QA_PAIRS + INSTRUCT:
        for _ in range(12):
            yield f"질문: {q}\n답변: {ans}"

    # 조합형 짧은 문장 (일부는 확정 조합으로 어휘 전수 노출)
    combos = list(product(SUBJECTS, ADVS[:6], OBJECTS, VERBS[:8]))
    r.shuffle(combos)
    for s, adv, o, v in combos[:3000]:
        yield f"{s} {adv} {o} {v}."

    # 무작위 다문장
    for _ in range(n_synth):
        k = r.randint(1, 4)
        yield " ".join(_sentence(r) for _ in range(k))
