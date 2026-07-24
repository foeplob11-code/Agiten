"""Agiten 트랜스포머 — 순수 PyTorch 구현.

사전학습된 가중치를 일절 쓰지 않는다. 구조는 현대 디코더 표준을 따른다:
RMSNorm(pre-norm) + RoPE + GQA + SwiGLU + 임베딩 가중치 공유.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class ModelConfig:
    vocab_size: int = 32768
    dim: int = 768
    n_layers: int = 12
    n_heads: int = 12
    n_kv_heads: int = 4          # GQA: n_heads 의 약수
    ffn_dim: int = 2048          # SwiGLU 중간 차원
    max_seq_len: int = 2048
    rope_theta: float = 10000.0
    norm_eps: float = 1e-5
    dropout: float = 0.0
    tie_embeddings: bool = True

    @property
    def head_dim(self) -> int:
        return self.dim // self.n_heads

    def n_params(self) -> int:
        """임베딩 포함 총 파라미터 수 (해석용 근사가 아닌 정확한 계산)."""
        emb = self.vocab_size * self.dim
        attn = (
            self.dim * self.dim                                  # q
            + 2 * self.dim * (self.n_kv_heads * self.head_dim)   # k, v
            + self.dim * self.dim                                # o
        )
        ffn = 3 * self.dim * self.ffn_dim                        # gate, up, down
        norms = 2 * self.dim
        per_layer = attn + ffn + norms
        total = emb + self.n_layers * per_layer + self.dim       # + final norm
        if not self.tie_embeddings:
            total += self.vocab_size * self.dim
        return total

    def validate(self) -> None:
        assert self.dim % self.n_heads == 0, "dim 은 n_heads 로 나누어떨어져야 함"
        assert self.n_heads % self.n_kv_heads == 0, "n_heads 는 n_kv_heads 의 배수여야 함"


# ---------------------------------------------------------------- 구성 요소

class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float = 1e-5):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        dtype = x.dtype
        x = x.float()
        x = x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)
        return (x * self.weight.float()).to(dtype)


def build_rope_cache(seq_len: int, head_dim: int, theta: float, device, dtype):
    freqs = 1.0 / (theta ** (torch.arange(0, head_dim, 2, device=device).float() / head_dim))
    t = torch.arange(seq_len, device=device).float()
    angles = torch.outer(t, freqs)                       # (T, hd/2)
    return torch.cos(angles).to(dtype), torch.sin(angles).to(dtype)


def apply_rope(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    """x: (B, H, T, hd) — 짝/홀 채널을 쌍으로 회전."""
    x1, x2 = x[..., 0::2], x[..., 1::2]
    cos = cos[None, None, :, :]
    sin = sin[None, None, :, :]
    out = torch.stack([x1 * cos - x2 * sin, x1 * sin + x2 * cos], dim=-1)
    return out.flatten(-2)


class Attention(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.n_heads = cfg.n_heads
        self.n_kv_heads = cfg.n_kv_heads
        self.head_dim = cfg.head_dim
        self.n_rep = cfg.n_heads // cfg.n_kv_heads

        self.wq = nn.Linear(cfg.dim, cfg.n_heads * self.head_dim, bias=False)
        self.wk = nn.Linear(cfg.dim, cfg.n_kv_heads * self.head_dim, bias=False)
        self.wv = nn.Linear(cfg.dim, cfg.n_kv_heads * self.head_dim, bias=False)
        self.wo = nn.Linear(cfg.n_heads * self.head_dim, cfg.dim, bias=False)
        self.dropout = cfg.dropout

    def forward(self, x, cos, sin, cache=None):
        B, T, _ = x.shape

        q = self.wq(x).view(B, T, self.n_heads, self.head_dim).transpose(1, 2)
        k = self.wk(x).view(B, T, self.n_kv_heads, self.head_dim).transpose(1, 2)
        v = self.wv(x).view(B, T, self.n_kv_heads, self.head_dim).transpose(1, 2)

        q = apply_rope(q, cos, sin)
        k = apply_rope(k, cos, sin)

        if cache is not None:
            past_k, past_v = cache
            if past_k is not None:
                k = torch.cat([past_k, k], dim=2)
                v = torch.cat([past_v, v], dim=2)
            new_cache = (k, v)
        else:
            new_cache = None

        if self.n_rep > 1:
            k = k.repeat_interleave(self.n_rep, dim=1)
            v = v.repeat_interleave(self.n_rep, dim=1)

        # 캐시 사용 중 T==1 이면 마스크 불필요, 아니면 causal
        is_causal = cache is None or T > 1
        out = F.scaled_dot_product_attention(
            q, k, v,
            dropout_p=self.dropout if self.training else 0.0,
            is_causal=is_causal,
        )
        out = out.transpose(1, 2).contiguous().view(B, T, -1)
        return self.wo(out), new_cache


class FeedForward(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.w_gate = nn.Linear(cfg.dim, cfg.ffn_dim, bias=False)
        self.w_up = nn.Linear(cfg.dim, cfg.ffn_dim, bias=False)
        self.w_down = nn.Linear(cfg.ffn_dim, cfg.dim, bias=False)

    def forward(self, x):
        return self.w_down(F.silu(self.w_gate(x)) * self.w_up(x))


class Block(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.attn_norm = RMSNorm(cfg.dim, cfg.norm_eps)
        self.attn = Attention(cfg)
        self.ffn_norm = RMSNorm(cfg.dim, cfg.norm_eps)
        self.ffn = FeedForward(cfg)

    def forward(self, x, cos, sin, cache=None):
        h, new_cache = self.attn(self.attn_norm(x), cos, sin, cache)
        x = x + h
        x = x + self.ffn(self.ffn_norm(x))
        return x, new_cache


# ---------------------------------------------------------------- 본체

class Agiten(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        cfg.validate()
        self.cfg = cfg

        self.tok_emb = nn.Embedding(cfg.vocab_size, cfg.dim)
        self.blocks = nn.ModuleList(Block(cfg) for _ in range(cfg.n_layers))
        self.norm = RMSNorm(cfg.dim, cfg.norm_eps)
        self.lm_head = nn.Linear(cfg.dim, cfg.vocab_size, bias=False)
        if cfg.tie_embeddings:
            self.lm_head.weight = self.tok_emb.weight

        self.grad_checkpointing = False
        self._rope_device = None

        self.apply(self._init_weights)
        # 잔차 경로 출력층은 깊이에 맞춰 축소 (GPT-2 이후 표준)
        scale = 1.0 / math.sqrt(2 * cfg.n_layers)
        for name, p in self.named_parameters():
            if name.endswith("wo.weight") or name.endswith("w_down.weight"):
                nn.init.normal_(p, mean=0.0, std=0.02 * scale)

    def _init_weights(self, module):
        if isinstance(module, nn.Linear):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if module.bias is not None:
                nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def _rope(self, seq_len: int, device, dtype, offset: int = 0):
        if self._rope_device != device:
            cos, sin = build_rope_cache(
                self.cfg.max_seq_len, self.cfg.head_dim, self.cfg.rope_theta, device, torch.float32
            )
            self.register_buffer("_cos", cos, persistent=False)
            self.register_buffer("_sin", sin, persistent=False)
            self._rope_device = device
        return (self._cos[offset:offset + seq_len].to(dtype),
                self._sin[offset:offset + seq_len].to(dtype))

    def forward(self, idx, targets=None, loss_mask=None, caches=None, offset=0):
        """idx: (B, T) 토큰. targets: (B, T) 다음 토큰(-100 은 무시).

        loss_mask: (B, T) 1/0 — assistant 구간만 학습할 때 사용.
        """
        B, T = idx.shape
        x = self.tok_emb(idx)
        cos, sin = self._rope(T, x.device, x.dtype, offset)

        new_caches = [] if caches is not None else None
        for i, block in enumerate(self.blocks):
            cache = caches[i] if caches is not None else None
            if self.grad_checkpointing and self.training:
                x, nc = torch.utils.checkpoint.checkpoint(
                    block, x, cos, sin, cache, use_reentrant=False
                )
            else:
                x, nc = block(x, cos, sin, cache)
            if new_caches is not None:
                new_caches.append(nc)

        x = self.norm(x)
        logits = self.lm_head(x)

        loss = None
        if targets is not None:
            flat_logits = logits.view(-1, logits.size(-1)).float()
            flat_targets = targets.reshape(-1)
            if loss_mask is not None:
                flat_targets = flat_targets.masked_fill(loss_mask.reshape(-1) == 0, -100)
            # reduction='sum' 후 유효 토큰 수로 직접 나눈다.
            # 배치 전체가 마스킹되어도(유효 토큰 0) NaN 대신 0 을 반환.
            per_tok = F.cross_entropy(
                flat_logits, flat_targets, ignore_index=-100, reduction="sum"
            )
            valid = (flat_targets != -100).sum().clamp(min=1)
            loss = per_tok / valid

        return logits, loss, new_caches

    # ------------------------------------------------------------ 생성

    @torch.no_grad()
    def generate(self, idx, max_new_tokens=256, temperature=0.7, top_p=0.9,
                 top_k=50, stop_ids=(), repetition_penalty=1.05):
        self.eval()
        caches = [None] * self.cfg.n_layers
        offset = 0
        cur = idx
        generated: list[int] = []

        for _ in range(max_new_tokens):
            window = cur[:, -self.cfg.max_seq_len:]
            logits, _, caches = self(window, caches=caches, offset=offset)
            offset += window.shape[1]
            logits = logits[:, -1, :].float()

            if repetition_penalty != 1.0 and generated:
                for t in set(generated[-128:]):
                    logits[0, t] /= repetition_penalty

            if temperature <= 0:
                nxt = logits.argmax(-1, keepdim=True)
            else:
                logits = logits / temperature
                if top_k:
                    kth = torch.topk(logits, min(top_k, logits.size(-1)))[0][..., -1, None]
                    logits = logits.masked_fill(logits < kth, float("-inf"))
                probs = F.softmax(logits, dim=-1)
                if top_p < 1.0:
                    sorted_probs, sorted_idx = torch.sort(probs, descending=True, dim=-1)
                    cumsum = sorted_probs.cumsum(-1)
                    drop = cumsum - sorted_probs > top_p
                    sorted_probs[drop] = 0.0
                    sorted_probs /= sorted_probs.sum(-1, keepdim=True)
                    choice = torch.multinomial(sorted_probs, 1)
                    nxt = sorted_idx.gather(-1, choice)
                else:
                    nxt = torch.multinomial(probs, 1)

            token = int(nxt.item())
            generated.append(token)
            if token in stop_ids:
                break
            cur = nxt  # 캐시가 있으므로 마지막 토큰만 넣는다

        return generated
