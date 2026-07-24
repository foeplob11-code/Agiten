"""데이터셋 빌드 진입점.

생성물(data/processed/):
  sft.jsonl    — 에이전트 대화. {messages:[...], text:"<렌더링 전체>"}
  sft_val.jsonl
  corpus.jsonl — 토크나이저 학습 + (선택) 프리트레인용 순수 텍스트 {text:...}

사용:
  python -m agiten.datagen.build --n 20000 --out data/processed
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from ..protocol import render, to_dict, DEFAULT_SYSTEM, Message
from ..toolspec import render_catalog
from .generators import iter_dialogs
from .corpus import iter_corpus_lines


def _with_system(dialog: list[Message], r: random.Random) -> list[Message]:
    """대화 앞에 시스템 프롬프트(+가끔 도구 카탈로그)를 붙인다."""
    if r.random() < 0.5:
        sys = DEFAULT_SYSTEM + "\n\n사용 가능한 도구:\n" + render_catalog()
    else:
        sys = DEFAULT_SYSTEM
    return [Message(role="system", content=sys)] + dialog


def build_sft(n: int, out_dir: Path, val_ratio: float, seed: int) -> None:
    r = random.Random(seed)
    n_val = int(n * val_ratio)

    train_f = (out_dir / "sft.jsonl").open("w", encoding="utf-8")
    val_f = (out_dir / "sft_val.jsonl").open("w", encoding="utf-8")

    for i, dialog in enumerate(iter_dialogs(n, seed=seed)):
        full = _with_system(dialog, r)
        text = render(full, add_bos=True, add_eos=True)
        row = json.dumps(
            {"messages": [to_dict(m) for m in full], "text": text},
            ensure_ascii=False,
        )
        (val_f if i < n_val else train_f).write(row + "\n")

    train_f.close()
    val_f.close()
    print(f"[sft] train={n - n_val}  val={n_val}  -> {out_dir}")


def build_corpus(n_dialogs: int, out_dir: Path, seed: int) -> None:
    """토크나이저/프리트레인용 텍스트. 대화 렌더링 + 코드·자연어 스니펫."""
    path = out_dir / "corpus.jsonl"
    count = 0
    with path.open("w", encoding="utf-8") as f:
        # 1) 대화도 코퍼스에 포함 (특수 토큰 노출)
        for dialog in iter_dialogs(n_dialogs, seed=seed + 1):
            text = render(dialog, add_bos=True, add_eos=True)
            f.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
            count += 1
        # 2) 순수 텍스트/코드 스니펫
        for line in iter_corpus_lines(seed=seed + 2):
            f.write(json.dumps({"text": line}, ensure_ascii=False) + "\n")
            count += 1
    print(f"[corpus] lines={count} -> {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20000, help="SFT 대화 수")
    ap.add_argument("--corpus-n", type=int, default=8000, help="코퍼스에 넣을 대화 수")
    ap.add_argument("--val-ratio", type=float, default=0.02)
    ap.add_argument("--out", type=str, default="data/processed")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    build_sft(args.n, out_dir, args.val_ratio, args.seed)
    build_corpus(args.corpus_n, out_dir, args.seed)
    print("완료.")


if __name__ == "__main__":
    main()
