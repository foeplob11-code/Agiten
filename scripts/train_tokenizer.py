"""토크나이저 학습 — 우리 코퍼스로 BPE vocab 을 처음부터 만든다.

사용:
  python scripts/train_tokenizer.py \
      --corpus data/processed/corpus.jsonl \
      --sft data/processed/sft.jsonl \
      --vocab-size 32768 --out tokenizer.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agiten.tokenizer import AgitenTokenizer, iter_corpus_texts
from agiten import hubsync


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=str, default="data/processed/corpus.jsonl")
    ap.add_argument("--sft", type=str, default="data/processed/sft.jsonl")
    ap.add_argument("--vocab-size", type=int, default=32768)
    ap.add_argument("--out", type=str, default="tokenizer.json")
    ap.add_argument("--hf-repo", default=None, help="토크나이저를 보관할 HF 저장소")
    args = ap.parse_args()

    # Hub 에 이미 있으면 내려받아 재사용(데이터가 결정적이므로 유효)
    if args.hf_repo:
        hubsync.ensure_repo(args.hf_repo, private=True)
        if hubsync.download(args.hf_repo, "tokenizer.json", args.out):
            tok = AgitenTokenizer.load(args.out)
            print(f"Hub 토크나이저 재사용  vocab={tok.vocab_size}")
            return

    paths = [p for p in [args.corpus, args.sft] if p and Path(p.split(",")[0]).exists()]
    if not paths:
        raise SystemExit("코퍼스를 찾을 수 없습니다. 먼저 데이터를 빌드하세요.")

    print(f"토크나이저 학습 시작: {paths}  vocab={args.vocab_size}")
    tok = AgitenTokenizer.train(iter_corpus_texts(paths), vocab_size=args.vocab_size)
    tok.save(args.out)
    print(f"저장 완료 -> {args.out}  실제 vocab={tok.vocab_size}")
    if args.hf_repo:
        hubsync.upload(args.hf_repo, args.out, "tokenizer.json")
    # 특수 토큰 라운드트립 점검
    for t in ["<|assistant|>", "<|call|>", "<|end|>"]:
        tid = tok.token_to_id(t)
        assert tid is not None, f"특수 토큰 누락: {t}"
    print("특수 토큰 정상.")


if __name__ == "__main__":
    main()
