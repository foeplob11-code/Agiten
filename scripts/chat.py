"""학습한 Agiten 과 대화 — 추론 진입점.

학습과 동일한 protocol.render_prompt 로 프롬프트를 만들고,
생성 결과를 protocol.parse_assistant 로 파싱해 툴콜을 보여준다.

단발:
  python scripts/chat.py --ckpt runs/base-sft/ckpt_last.pt --message "안녕"
대화형:
  python scripts/chat.py --ckpt runs/base-sft/ckpt_last.pt --interactive
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agiten.model import Agiten, ModelConfig
from agiten.protocol import (
    Message, render_prompt, parse_assistant,
    DEFAULT_SYSTEM, END, EOS,
)
from agiten.toolspec import render_catalog, CONFIRM_REQUIRED
from agiten.tokenizer import AgitenTokenizer


def load_model(ckpt_path: str, device: str) -> tuple[Agiten, ModelConfig]:
    ck = torch.load(ckpt_path, map_location=device)
    cfg = ModelConfig(**ck["cfg"])
    model = Agiten(cfg).to(device)
    model.load_state_dict(ck["model"])
    model.eval()
    return model, cfg


def generate_reply(model, tok, messages, device, cfg,
                   temperature=0.7, max_new_tokens=256) -> Message:
    prompt = render_prompt(messages)
    ids = tok.encode(prompt)[-cfg.max_seq_len:]
    x = torch.tensor([ids], device=device)
    out_ids = model.generate(
        x, max_new_tokens=max_new_tokens, temperature=temperature,
        top_p=0.9, top_k=50, stop_ids=(tok.end_id, tok.eos_id),
    )
    text = tok.decode(out_ids, skip_special=False)
    return parse_assistant(text)


def show(reply: Message) -> None:
    if reply.think:
        print(f"  \033[90m(생각: {reply.think})\033[0m")
    if reply.content:
        print(f"Agiten> {reply.content}")
    for c in reply.calls:
        mark = "  [확인필요]" if c.name in CONFIRM_REQUIRED else ""
        print(f"  \033[36m⚙ 도구호출 {c.name}({c.args}){mark}\033[0m")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--tokenizer", default="tokenizer.json")
    ap.add_argument("--preset", default=None, help="호환용(무시). cfg 는 체크포인트에서 읽음")
    ap.add_argument("--message", default=None)
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--with-tools", action="store_true",
                    help="시스템 프롬프트에 도구 카탈로그 포함")
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AgitenTokenizer.load(args.tokenizer)
    model, cfg = load_model(args.ckpt, device)
    print(f"모델 로드: {cfg.n_params()/1e6:.1f}M params  device={device}\n")

    sys_content = DEFAULT_SYSTEM
    if args.with_tools:
        sys_content += "\n\n사용 가능한 도구:\n" + render_catalog()
    history = [Message(role="system", content=sys_content)]

    if args.message:
        history.append(Message(role="user", content=args.message))
        print(f"You> {args.message}")
        reply = generate_reply(model, tok, history, device, cfg, args.temperature)
        show(reply)
        return

    if args.interactive:
        print("대화형 모드. 'exit' 로 종료.\n")
        while True:
            try:
                msg = input("You> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if msg in ("exit", "quit", "종료"):
                break
            if not msg:
                continue
            history.append(Message(role="user", content=msg))
            reply = generate_reply(model, tok, history, device, cfg, args.temperature)
            show(reply)
            history.append(reply)
        return

    print("--message 또는 --interactive 를 지정하세요.")


if __name__ == "__main__":
    main()
