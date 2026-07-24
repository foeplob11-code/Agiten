"""Agiten 학습 루프 — 프리트레인과 SFT 를 한 스크립트로.

'학습만 켜놓으면 되게' 만드는 게 목표라 다음을 자동 처리한다:
  · 체크포인트 자동 저장 + 재시작(--resume) → Colab 끊겨도 이어감
  · AMP(bf16/fp16) 자동 선택, gradient checkpointing, grad accumulation
  · cosine LR + warmup, grad clip
  · 주기적 검증 loss 출력

사용:
  # 1단계 프리트레인
  python scripts/train.py --stage pretrain --preset base --steps 20000 \
      --data data/processed/corpus.jsonl --out runs/base

  # 2단계 SFT (프리트레인 체크포인트에서 이어서)
  python scripts/train.py --stage sft --preset base --steps 4000 \
      --data data/processed/sft.jsonl --init runs/base/ckpt_last.pt --out runs/base_sft
"""

from __future__ import annotations

import argparse
import math
import os
import time
from pathlib import Path

import torch
from torch.utils.data import DataLoader

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agiten.data import PackedCorpus, SFTDataset, collate
from agiten.model import Agiten
from agiten.tokenizer import AgitenTokenizer
from agiten import hubsync
from configs.sizes import make_config


# ---------------------------------------------------------------- 유틸

def lr_at(step: int, warmup: int, total: int, peak: float, floor_ratio=0.1) -> float:
    if step < warmup:
        return peak * step / max(1, warmup)
    prog = (step - warmup) / max(1, total - warmup)
    prog = min(1.0, prog)
    return peak * (floor_ratio + (1 - floor_ratio) * 0.5 * (1 + math.cos(math.pi * prog)))


def pick_amp():
    if not torch.cuda.is_available():
        return torch.float32, False
    if torch.cuda.is_bf16_supported():
        return torch.bfloat16, True
    return torch.float16, True


def save_ckpt(path, model, opt, step, cfg, extra=None):
    torch.save({
        "model": model.state_dict(),
        "opt": opt.state_dict(),
        "step": step,
        "cfg": cfg.__dict__,
        "extra": extra or {},
    }, path)


# ---------------------------------------------------------------- 메인

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["pretrain", "sft"], required=True)
    ap.add_argument("--preset", default="base")
    ap.add_argument("--data", required=True)
    ap.add_argument("--val", default=None)
    ap.add_argument("--tokenizer", default="tokenizer.json")
    ap.add_argument("--out", default="runs/exp")
    ap.add_argument("--init", default=None, help="이어받을 가중치(sft 시작점 등)")
    ap.add_argument("--resume", action="store_true", help="out/ckpt_last.pt 에서 재개")
    ap.add_argument("--steps", type=int, default=20000)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--accum", type=int, default=4, help="grad accumulation")
    ap.add_argument("--seq-len", type=int, default=None)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--warmup", type=int, default=500)
    ap.add_argument("--wd", type=float, default=0.1)
    ap.add_argument("--clip", type=float, default=1.0)
    ap.add_argument("--save-every", type=int, default=500)
    ap.add_argument("--eval-every", type=int, default=500)
    ap.add_argument("--log-every", type=int, default=20)
    ap.add_argument("--grad-ckpt", action="store_true")
    # Hugging Face Hub 동기화(구글 드라이브 대신). 예: hobak/agiten-ckpts
    ap.add_argument("--hf-repo", default=None,
                    help="체크포인트를 올릴 HF 저장소. 설정 시 자동 업로드/재개")
    ap.add_argument("--hf-private", action="store_true", default=True)
    ap.add_argument("--hf-every", type=int, default=1,
                    help="체크포인트 저장 N회마다 1번 업로드(용량 큰 모델 절약용)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    amp_dtype, use_amp = pick_amp()
    print(f"device={device}  amp={amp_dtype if use_amp else 'off'}")

    tok = AgitenTokenizer.load(args.tokenizer)
    cfg = make_config(args.preset, vocab_size=tok.vocab_size)
    if args.seq_len:
        cfg.max_seq_len = args.seq_len
    seq_len = cfg.max_seq_len
    print(f"모델: {args.preset}  {cfg.n_params()/1e6:.1f}M params  seq_len={seq_len}")

    # 데이터
    if args.stage == "pretrain":
        ds = PackedCorpus(args.data, tok, seq_len)
    else:
        ds = SFTDataset(args.data, tok, seq_len)
    dl = DataLoader(ds, batch_size=args.batch, shuffle=True,
                    collate_fn=collate, drop_last=True, num_workers=2)
    print(f"데이터셋 샘플 수: {len(ds)}  (배치 {args.batch} x 누적 {args.accum})")

    val_dl = None
    if args.val and Path(args.val).exists():
        val_ds = (PackedCorpus if args.stage == "pretrain" else SFTDataset)(args.val, tok, seq_len)
        val_dl = DataLoader(val_ds, batch_size=args.batch, collate_fn=collate)

    # 모델
    model = Agiten(cfg).to(device)
    if args.grad_ckpt:
        model.grad_checkpointing = True

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr,
                            betas=(0.9, 0.95), weight_decay=args.wd)
    scaler = torch.cuda.amp.GradScaler(enabled=(use_amp and amp_dtype == torch.float16))

    # HF Hub 준비 + 재개용 체크포인트 내려받기(로컬에 없으면)
    hub_on = hubsync.enabled(args.hf_repo)
    if hub_on:
        hubsync.ensure_repo(args.hf_repo, private=args.hf_private)
        if args.resume and not (out / "ckpt_last.pt").exists():
            hubsync.download(args.hf_repo, hubsync.repo_path_for(out),
                             out / "ckpt_last.pt")

    start_step = 0
    # 이어받기 (SFT 초기화 / 재개)
    if args.resume and (out / "ckpt_last.pt").exists():
        ck = torch.load(out / "ckpt_last.pt", map_location=device)
        model.load_state_dict(ck["model"])
        opt.load_state_dict(ck["opt"])
        start_step = ck["step"]
        print(f"재개: step={start_step}")
    elif args.init and Path(args.init).exists():
        ck = torch.load(args.init, map_location=device)
        model.load_state_dict(ck["model"], strict=False)
        print(f"가중치 초기화: {args.init}")
    elif args.init and hub_on:
        # init 파일이 로컬에 없으면 Hub 에서 시도(예: pretrain 체크포인트)
        tmp = out / "_init.pt"
        if hubsync.download(args.hf_repo, hubsync.repo_path_for(Path(args.init).parent),
                            tmp):
            ck = torch.load(tmp, map_location=device)
            model.load_state_dict(ck["model"], strict=False)
            print(f"가중치 초기화(Hub): {args.init}")

    save_count = 0

    def checkpoint(step_now: int, *, final: bool = False):
        """로컬 저장 + (설정 시) Hub 업로드."""
        nonlocal save_count
        save_ckpt(out / "ckpt_last.pt", model, opt, step_now, cfg)
        if final:
            save_ckpt(out / "ckpt_final.pt", model, opt, step_now, cfg)
        if hub_on:
            save_count += 1
            if final or save_count % args.hf_every == 0:
                hubsync.upload(args.hf_repo, out / "ckpt_last.pt",
                               hubsync.repo_path_for(out))

    model.train()
    data_iter = iter(dl)
    t0 = time.time()
    running = 0.0

    for step in range(start_step, args.steps):
        lr = lr_at(step, args.warmup, args.steps, args.lr)
        for g in opt.param_groups:
            g["lr"] = lr

        opt.zero_grad(set_to_none=True)
        loss_val = 0.0
        for _ in range(args.accum):
            try:
                x, y, m = next(data_iter)
            except StopIteration:
                data_iter = iter(dl)
                x, y, m = next(data_iter)
            x, y, m = x.to(device), y.to(device), m.to(device)
            with torch.autocast(device_type="cuda", dtype=amp_dtype, enabled=use_amp):
                _, loss, _ = model(x, targets=y, loss_mask=m)
                loss = loss / args.accum
            scaler.scale(loss).backward()
            loss_val += loss.item()

        scaler.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(model.parameters(), args.clip)
        scaler.step(opt)
        scaler.update()
        running += loss_val

        if step % args.log_every == 0 and step > start_step:
            avg = running / args.log_every
            running = 0.0
            dt = time.time() - t0
            toks = args.log_every * args.batch * args.accum * seq_len
            print(f"step {step:6d} | loss {avg:.4f} | lr {lr:.2e} | "
                  f"{toks/dt:,.0f} tok/s")
            t0 = time.time()

        if val_dl is not None and step % args.eval_every == 0 and step > start_step:
            vloss = evaluate(model, val_dl, device, amp_dtype, use_amp)
            print(f"  [val] step {step} loss {vloss:.4f}")
            model.train()

        if step % args.save_every == 0 and step > start_step:
            checkpoint(step)
            print(f"  체크포인트 저장: step {step}")

    checkpoint(args.steps, final=True)
    print(f"학습 완료 -> {out}/ckpt_final.pt")


@torch.no_grad()
def evaluate(model, dl, device, amp_dtype, use_amp, max_batches=50):
    model.eval()
    total, n = 0.0, 0
    for i, (x, y, m) in enumerate(dl):
        if i >= max_batches:
            break
        x, y, m = x.to(device), y.to(device), m.to(device)
        with torch.autocast(device_type="cuda", dtype=amp_dtype, enabled=use_amp):
            _, loss, _ = model(x, targets=y, loss_mask=m)
        total += loss.item()
        n += 1
    return total / max(1, n)


if __name__ == "__main__":
    main()
