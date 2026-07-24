"""Agiten 자동화 에이전트 — 모델의 판단을 실제로 실행한다.

  단발 :  python scripts/agent.py --ckpt runs/smoke-sft/ckpt_last.pt --message "..."
  대화형:  python scripts/agent.py --ckpt ... --interactive
  무인 :  python scripts/agent.py --ckpt ... --message "..." --yes   # 확인 자동승인(주의)

안전:
  · 되돌릴 수 없는 도구/셸은 실행 전 [y/N] 확인을 받는다(--yes 면 자동승인).
  · 위험 명령(rm -rf / 등)은 --yes 여도 차단.
  · 파일 작업은 --workspace 안으로 제한.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agiten.model import Agiten, ModelConfig
from agiten.tokenizer import AgitenTokenizer
from agiten.runtime.executor import Executor, NEEDS_APPROVAL
from agiten.runtime.agent import Agent, ModelPolicy

C = {"call": "\033[36m", "res": "\033[90m", "final": "\033[32m",
     "think": "\033[90m", "warn": "\033[33m", "end": "\033[0m"}


def load(ckpt, device):
    ck = torch.load(ckpt, map_location=device)
    cfg = ModelConfig(**ck["cfg"])
    m = Agiten(cfg).to(device); m.load_state_dict(ck["model"]); m.eval()
    return m, cfg


def make_events():
    def on_event(kind, data):
        if kind == "assistant" and getattr(data, "think", ""):
            print(f"  {C['think']}(생각: {data.think}){C['end']}")
        elif kind == "call":
            print(f"  {C['call']}⚙ {data.name}({data.args}){C['end']}")
        elif kind == "result":
            print(f"  {C['res']}← {data[:120]}{C['end']}")
        elif kind == "final":
            print(f"{C['final']}Agiten> {data}{C['end']}")
        elif kind == "max_steps":
            print(f"  {C['warn']}(최대 단계 도달){C['end']}")
    return on_event


def make_confirm(auto: bool):
    def confirm(call, preview):
        if auto:
            print(f"  {C['warn']}[자동승인] {preview}{C['end']}")
            return True
        ans = input(f"  {C['warn']}⚠ {preview}  실행할까요? [y/N] {C['end']}").strip().lower()
        return ans in ("y", "yes", "ㅇ", "응")
    return confirm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--tokenizer", default="tokenizer.json")
    ap.add_argument("--workspace", default="runtime/workspace")
    ap.add_argument("--message")
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument("--yes", action="store_true", help="확인 자동승인(무인 자동화용, 주의)")
    ap.add_argument("--max-steps", type=int, default=6)
    ap.add_argument("--temperature", type=float, default=0.6)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AgitenTokenizer.load(args.tokenizer)
    model, cfg = load(args.ckpt, device)
    print(f"모델 로드: {cfg.n_params()/1e6:.1f}M · 작업폴더: {args.workspace}\n")

    executor = Executor(
        workspace=args.workspace,
        confirm_cb=make_confirm(args.yes),
        auto_approve=set(NEEDS_APPROVAL) if args.yes else set(),
    )
    policy = ModelPolicy(model, tok, cfg, temperature=args.temperature)
    agent = Agent(policy, executor, max_steps=args.max_steps, on_event=make_events())

    if args.message:
        agent.run(args.message)
        return
    if args.interactive:
        print("자동화 에이전트 대화형. 'exit' 종료.\n")
        history = None
        while True:
            try:
                msg = input("You> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if msg in ("exit", "quit", "종료"):
                break
            if msg:
                history = agent.run(msg, history)
        return
    print("--message 또는 --interactive 를 지정하세요.")


if __name__ == "__main__":
    main()
