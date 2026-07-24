"""실제 프리트레인 코퍼스 내려받기 (Colab/네트워크 환경에서 실행).

합성 데이터만으로는 언어 유창성·어휘가 부족하다. 공개 코퍼스(한국어 위키 + 코드)를
스트리밍으로 받아 data/processed/corpus_real.jsonl 로 저장한다.
이후 토크나이저 학습과 프리트레인에서 corpus.jsonl 과 함께 쓴다.

의존: pip install datasets
사용:
  python scripts/fetch_pretrain.py --ko-docs 40000 --code-docs 20000 \
      --out data/processed/corpus_real.jsonl

주의: 데이터 다운로드는 되돌릴 수 없는 대량 네트워크 작업이다. 규모는 --*-docs 로 조절.
라이선스: 한국어 위키(CC BY-SA), code_search_net(공개) — 사용 시 각 라이선스 확인.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _clean(text: str, min_len: int = 40, max_chars: int = 4000) -> str | None:
    text = (text or "").strip()
    if len(text) < min_len:
        return None
    return text[:max_chars]


def stream_korean(n: int):
    """한국어 위키백과 본문."""
    from datasets import load_dataset
    ds = load_dataset("wikimedia/wikipedia", "20231101.ko",
                      split="train", streaming=True)
    got = 0
    for row in ds:
        t = _clean(row.get("text", ""))
        if t:
            yield t
            got += 1
            if got >= n:
                return


def stream_code(n: int):
    """공개 파이썬 코드(code_search_net)."""
    from datasets import load_dataset
    ds = load_dataset("code_search_net", "python",
                      split="train", streaming=True, trust_remote_code=True)
    got = 0
    for row in ds:
        t = _clean(row.get("whole_func_string") or row.get("func_code_string", ""),
                   min_len=20)
        if t:
            yield t
            got += 1
            if got >= n:
                return


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ko-docs", type=int, default=40000)
    ap.add_argument("--code-docs", type=int, default=20000)
    ap.add_argument("--out", type=str, default="data/processed/corpus_real.jsonl")
    ap.add_argument("--skip-code", action="store_true")
    ap.add_argument("--skip-ko", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8") as f:
        if not args.skip_ko:
            print(f"한국어 위키 {args.ko_docs}건 스트리밍…")
            for t in stream_korean(args.ko_docs):
                f.write(json.dumps({"text": t}, ensure_ascii=False) + "\n")
                n += 1
                if n % 5000 == 0:
                    print(f"  {n}건")
        if not args.skip_code:
            print(f"파이썬 코드 {args.code_docs}건 스트리밍…")
            for t in stream_code(args.code_docs):
                f.write(json.dumps({"text": t}, ensure_ascii=False) + "\n")
                n += 1
                if n % 5000 == 0:
                    print(f"  {n}건")
    print(f"완료: {n}건 -> {out}")
    print("이제 토크나이저/프리트레인에서 corpus.jsonl 과 함께 사용하세요:")
    print(f"  --corpus 'data/processed/corpus.jsonl,{out}'")


if __name__ == "__main__":
    main()
