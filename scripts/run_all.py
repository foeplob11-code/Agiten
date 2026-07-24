"""한 방에 전부 실행 — 데이터 → 토크나이저 → 프리트레인 → SFT.

복잡한 단계를 하나로 묶는다. 이거 하나만 돌리면 학습이 끝난다.

  python scripts/run_all.py                 # base(~100M) 전 과정
  python scripts/run_all.py --quick         # 10분 맛보기(smoke)
  python scripts/run_all.py --preset large  # 크기만 바꾸기
  python scripts/run_all.py --hf-repo 내아이디/agiten-ckpts   # HF에 저장/재개

끊겨도 같은 명령을 다시 실행하면 이어서 학습한다(--resume 내장).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 프리셋별 기본 학습 스텝(그냥 돌리면 되는 값)
# base 는 무료 Colab 에서도 현실적이도록 낮췄다(seq_len 1024, batch 8, accum 2 권장).
# 체크포인트를 HF 에 저장하며 여러 세션에 나눠 돌리는 것을 전제로 한다.
STEPS = {
    "smoke": (300, 200),
    "base": (3000, 5000),     # SFT 를 넉넉히 — 도구호출 유효성 학습이 관건
    "large": (40000, 8000),
    "xl": (60000, 10000),
}


def run(cmd: list[str]) -> None:
    print("\n$ " + " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(f"실패: {' '.join(cmd)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="base")
    ap.add_argument("--quick", action="store_true", help="smoke 프리셋으로 빠른 전 과정")
    ap.add_argument("--hf-repo", default=None, help="Hugging Face 저장소(선택)")
    ap.add_argument("--corpus", default="data/processed/corpus.jsonl",
                    help="쉼표로 실제 코퍼스 추가 가능")
    ap.add_argument("--n", type=int, default=60000, help="합성 대화 수")
    ap.add_argument("--pretrain-steps", type=int, default=None)
    ap.add_argument("--sft-steps", type=int, default=None)
    # CPU 등 느린 환경에서 배치/시퀀스를 줄여 속도를 높이는 용도
    ap.add_argument("--batch", type=int, default=None)
    ap.add_argument("--accum", type=int, default=None)
    ap.add_argument("--seq-len", type=int, default=None)
    # grad-checkpointing 은 큰 모델 메모리 절약용. 작은 모델엔 느리기만 해서 기본 끔.
    ap.add_argument("--grad-ckpt", action="store_true")
    args = ap.parse_args()

    bs = ["--batch", str(args.batch)] if args.batch else []
    ac = ["--accum", str(args.accum)] if args.accum else []
    sl = ["--seq-len", str(args.seq_len)] if args.seq_len else []
    gc = ["--grad-ckpt"] if args.grad_ckpt else []
    extra = bs + ac + sl + gc

    preset = "smoke" if args.quick else args.preset
    pt_steps, sft_steps = STEPS.get(preset, STEPS["base"])
    pt_steps = args.pretrain_steps or pt_steps
    sft_steps = args.sft_steps or sft_steps
    hf = ["--hf-repo", args.hf_repo] if args.hf_repo else []
    py = sys.executable

    print(f"=== Agiten 전 과정 시작: preset={preset} "
          f"(pretrain {pt_steps} / sft {sft_steps} 스텝) ===")

    # 1) 데이터 (없을 때만)
    if not (ROOT / "data/processed/sft.jsonl").exists():
        run([py, "-m", "agiten.datagen.build", "--n", str(args.n),
             "--corpus-n", "15000", "--out", "data/processed"])
    else:
        print("[1/4] 데이터 이미 있음 — 건너뜀")

    # 2) 토크나이저 (없을 때만; hf-repo 있으면 스크립트가 재사용 처리)
    if hf or not (ROOT / "tokenizer.json").exists():
        run([py, "scripts/train_tokenizer.py", "--corpus", args.corpus,
             "--sft", "data/processed/sft.jsonl", "--vocab-size", "32768",
             "--out", "tokenizer.json", *hf])
    else:
        print("[2/4] 토크나이저 이미 있음 — 건너뜀")

    # 3) 프리트레인
    run([py, "scripts/train.py", "--stage", "pretrain", "--preset", preset,
         "--data", args.corpus, "--tokenizer", "tokenizer.json",
         "--out", f"runs/{preset}-pt", "--resume",
         "--steps", str(pt_steps), *extra, *hf])

    # 4) SFT
    run([py, "scripts/train.py", "--stage", "sft", "--preset", preset,
         "--data", "data/processed/sft.jsonl",
         "--val", "data/processed/sft_val.jsonl",
         "--tokenizer", "tokenizer.json", "--out", f"runs/{preset}-sft",
         "--init", f"runs/{preset}-pt/ckpt_last.pt", "--resume",
         "--steps", str(sft_steps), "--lr", "1e-4", "--warmup", "200", *extra, *hf])

    print(f"\n=== 끝! 대화해보기 ===")
    print(f"{py} scripts/chat.py --ckpt runs/{preset}-sft/ckpt_last.pt "
          f"--tokenizer tokenizer.json --with-tools --interactive")


if __name__ == "__main__":
    main()
