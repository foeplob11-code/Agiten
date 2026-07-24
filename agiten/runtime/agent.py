"""에이전트 루프 — 모델과 실행기를 연결한다.

    사용자 요청 → 모델이 판단(도구호출) → 실행기가 실행 → 결과를 모델에 되먹임
                → 다음 판단 → ... → 최종 답변

policy(정책)는 '대화 이력을 받아 다음 assistant 메시지를 만드는 것'으로 추상화했다.
  · ModelPolicy : 학습한 Agiten 모델 사용
  · 테스트용 스크립트 정책도 끼울 수 있어, 모델 없이 루프 자체를 검증 가능.
"""

from __future__ import annotations

from typing import Callable, Protocol

from ..protocol import Message, DEFAULT_SYSTEM
from ..toolspec import render_catalog
from .executor import Executor


class Policy(Protocol):
    def act(self, messages: list[Message]) -> Message:
        """대화 이력을 받아 다음 assistant 메시지(내용/도구호출)를 만든다."""
        ...


EventCb = Callable[[str, object], None]


class Agent:
    def __init__(self, policy: Policy, executor: Executor,
                 max_steps: int = 6, with_tools_prompt: bool = True,
                 on_event: EventCb | None = None):
        self.policy = policy
        self.executor = executor
        self.max_steps = max_steps
        self.on_event = on_event or (lambda *_: None)
        sys = DEFAULT_SYSTEM
        if with_tools_prompt:
            sys += "\n\n사용 가능한 도구:\n" + render_catalog()
        self.system = Message(role="system", content=sys)

    def run(self, user_msg: str, history: list[Message] | None = None) -> list[Message]:
        messages = list(history) if history else [self.system]
        messages.append(Message(role="user", content=user_msg))
        self.on_event("user", user_msg)

        for step in range(self.max_steps):
            reply = self.policy.act(messages)
            messages.append(reply)
            self.on_event("assistant", reply)

            if not reply.calls:
                self.on_event("final", reply.content)
                return messages  # 도구호출 없으면 대화 종료

            # 도구호출 실행 → 결과를 tool 메시지로 되먹임
            for call in reply.calls:
                self.on_event("call", call)
                result = self.executor.execute(call)
                self.on_event("result", result)
                messages.append(Message(role="tool", content=result))

        self.on_event("max_steps", self.max_steps)
        return messages


# ---------------------------------------------------------------- 모델 정책

class ModelPolicy:
    """학습한 Agiten 모델을 정책으로 감싼다."""

    def __init__(self, model, tokenizer, cfg, temperature: float = 0.6,
                 max_new_tokens: int = 200):
        self.model = model
        self.tok = tokenizer
        self.cfg = cfg
        self.temperature = temperature
        self.max_new_tokens = max_new_tokens

    def act(self, messages: list[Message]) -> Message:
        import torch
        from ..protocol import render_prompt, parse_assistant

        prompt = render_prompt(messages)
        ids = self.tok.encode(prompt)[-self.cfg.max_seq_len:]
        device = next(self.model.parameters()).device
        x = torch.tensor([ids], device=device)
        out = self.model.generate(
            x, max_new_tokens=self.max_new_tokens, temperature=self.temperature,
            top_p=0.9, top_k=50, stop_ids=(self.tok.end_id, self.tok.eos_id),
        )
        text = self.tok.decode(out, skip_special=False)
        return parse_assistant(text)
