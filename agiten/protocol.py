"""Agiten 대화/툴콜 프로토콜.

학습과 추론이 **완전히 동일한** 문자열을 쓰도록 렌더링을 한곳에 모았다.
여기가 틀어지면 학습은 잘 되는데 추론에서 툴콜을 못 뱉는 현상이 생긴다.

포맷:
    <|bos|><|system|>...<|end|>
    <|user|>...<|end|>
    <|assistant|><|think|>...<|/think|><|call|>{"name":..,"args":{..}}<|/call|><|end|>
    <|tool|>{"ok":true,...}<|end|>
    <|assistant|>최종 답변<|end|><|eos|>
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

# ---------------------------------------------------------------- 특수 토큰

PAD = "<|pad|>"
BOS = "<|bos|>"
EOS = "<|eos|>"
SYSTEM = "<|system|>"
USER = "<|user|>"
ASSISTANT = "<|assistant|>"
TOOL = "<|tool|>"
END = "<|end|>"
THINK_OPEN = "<|think|>"
THINK_CLOSE = "<|/think|>"
CALL_OPEN = "<|call|>"
CALL_CLOSE = "<|/call|>"

SPECIAL_TOKENS: list[str] = [
    PAD, BOS, EOS,
    SYSTEM, USER, ASSISTANT, TOOL, END,
    THINK_OPEN, THINK_CLOSE,
    CALL_OPEN, CALL_CLOSE,
]

Role = Literal["system", "user", "assistant", "tool"]

DEFAULT_SYSTEM = (
    "너는 Agiten. 사용자가 밑바닥부터 직접 만들고 학습시킨 개인 비서 AI다. "
    "다른 회사의 모델이 아니라 사용자의 것이다. "
    "터미널, 파일/코드, 이메일, 메신저, 일정, 기억을 도구로 직접 다룬다. "
    "말투는 담백하다. 군더더기·과장·빈말 없이 핵심만 말한다. "
    "모르거나 못 하는 것은 솔직히 인정한다. "
    "필요할 때만 도구를 쓰고, 되돌릴 수 없는 작업은 실행 전에 반드시 확인을 받는다."
)


# ---------------------------------------------------------------- 메시지 구조

@dataclass
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        body = json.dumps({"name": self.name, "args": self.args}, ensure_ascii=False)
        return f"{CALL_OPEN}{body}{CALL_CLOSE}"


@dataclass
class Message:
    role: Role
    content: str = ""
    think: str = ""
    calls: list[ToolCall] = field(default_factory=list)

    def render(self) -> str:
        if self.role == "system":
            return f"{SYSTEM}{self.content}{END}"
        if self.role == "user":
            return f"{USER}{self.content}{END}"
        if self.role == "tool":
            return f"{TOOL}{self.content}{END}"

        parts = [ASSISTANT]
        if self.think:
            parts.append(f"{THINK_OPEN}{self.think}{THINK_CLOSE}")
        if self.content:
            parts.append(self.content)
        for call in self.calls:
            parts.append(call.render())
        parts.append(END)
        return "".join(parts)


# ---------------------------------------------------------------- 직렬화

def render(messages: Iterable[Message], *, add_bos: bool = True, add_eos: bool = True) -> str:
    """학습용 전체 문자열."""
    body = "".join(m.render() for m in messages)
    return f"{BOS if add_bos else ''}{body}{EOS if add_eos else ''}"


def render_prompt(messages: Iterable[Message]) -> str:
    """추론용. 모델이 이어서 쓰도록 <|assistant|> 까지만 붙인다."""
    return f"{BOS}{''.join(m.render() for m in messages)}{ASSISTANT}"


def from_dict(d: dict[str, Any]) -> Message:
    return Message(
        role=d["role"],
        content=d.get("content", ""),
        think=d.get("think", ""),
        calls=[ToolCall(c["name"], c.get("args", {})) for c in d.get("calls", [])],
    )


def to_dict(m: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.role}
    if m.think:
        out["think"] = m.think
    if m.content:
        out["content"] = m.content
    if m.calls:
        out["calls"] = [{"name": c.name, "args": c.args} for c in m.calls]
    return out


# ---------------------------------------------------------------- 파싱 (추론)

def parse_assistant(text: str) -> Message:
    """모델이 생성한 <|assistant|> 이후 텍스트를 Message 로 되돌린다."""
    text = text.split(END)[0]

    think = ""
    if THINK_OPEN in text:
        head, _, rest = text.partition(THINK_OPEN)
        think, _, tail = rest.partition(THINK_CLOSE)
        text = head + tail

    calls: list[ToolCall] = []
    while CALL_OPEN in text:
        head, _, rest = text.partition(CALL_OPEN)
        payload, _, tail = rest.partition(CALL_CLOSE)
        try:
            obj = json.loads(payload)
            calls.append(ToolCall(obj["name"], obj.get("args", {})))
        except (json.JSONDecodeError, KeyError, TypeError):
            pass  # 망가진 툴콜은 버리고 텍스트로만 취급
        text = head + tail

    return Message(role="assistant", content=text.strip(), think=think.strip(), calls=calls)


# ---------------------------------------------------------------- 손실 마스킹

def assistant_spans(text: str) -> list[tuple[int, int]]:
    """assistant 응답 구간의 (start, end) 문자 오프셋.

    start 는 <|assistant|> **다음** 문자, end 는 <|end|> 를 포함한 위치.
    사용자 발화/툴 결과에는 loss 를 주지 않기 위해 쓴다.
    """
    spans: list[tuple[int, int]] = []
    cursor = 0
    while True:
        i = text.find(ASSISTANT, cursor)
        if i < 0:
            break
        start = i + len(ASSISTANT)
        j = text.find(END, start)
        if j < 0:
            spans.append((start, len(text)))
            break
        spans.append((start, j + len(END)))
        cursor = j + len(END)
    return spans
