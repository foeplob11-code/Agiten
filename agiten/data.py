"""학습용 데이터 파이프라인 — 토크나이즈 + 패킹 + 손실 마스크.

두 가지 모드:
  PackedCorpus : 프리트레인. 전체 토큰을 이어붙여 고정 길이로 자른다.
  SFTDataset   : 파인튜닝. 대화 하나 = 샘플 하나. assistant 구간만 loss.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import torch
from torch.utils.data import Dataset

from .protocol import ASSISTANT, END, assistant_spans
from .tokenizer import AgitenTokenizer


# ---------------------------------------------------------------- 프리트레인

class PackedCorpus(Dataset):
    """corpus.jsonl 의 'text' 를 전부 토큰화해 seq_len 블록으로 패킹."""

    def __init__(self, path: str | Path, tok: AgitenTokenizer, seq_len: int):
        self.seq_len = seq_len
        ids: list[int] = []
        # 쉼표로 여러 코퍼스 파일을 이어붙일 수 있다(합성 + 실제 코퍼스).
        paths = [p.strip() for p in str(path).split(",") if p.strip()]
        for pth in paths:
            with open(pth, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    text = json.loads(line)["text"]
                    ids.extend(tok.encode(text))
                    ids.append(tok.eos_id)
        # seq_len+1 로 나누어떨어지게 자르기 (입력/타깃 한 칸 시프트)
        n = (len(ids) - 1) // seq_len
        self.data = torch.tensor(ids[: n * seq_len + 1], dtype=torch.long)
        self.n = n

    def __len__(self) -> int:
        return self.n

    def __getitem__(self, i: int):
        s = i * self.seq_len
        x = self.data[s: s + self.seq_len]
        y = self.data[s + 1: s + self.seq_len + 1]
        mask = torch.ones_like(x)
        return x, y, mask


# ---------------------------------------------------------------- SFT

class SFTDataset(Dataset):
    """sft.jsonl. 각 대화를 토큰화하고 assistant 응답에만 loss 마스크."""

    def __init__(self, path: str | Path, tok: AgitenTokenizer, seq_len: int):
        self.tok = tok
        self.seq_len = seq_len
        self.rows: list[dict] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self.rows.append(json.loads(line))

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, i: int):
        text = self.rows[i]["text"]
        ids = self.tok.encode(text)[: self.seq_len]

        # 문자 단위 assistant 구간을 토큰 마스크로 옮긴다.
        mask_ids = self._build_mask(text)[: self.seq_len]

        # 패딩
        pad = self.seq_len - len(ids)
        if pad > 0:
            ids = ids + [self.tok.pad_id] * pad
            mask_ids = mask_ids + [0] * pad

        x = torch.tensor(ids[:-1], dtype=torch.long)
        y = torch.tensor(ids[1:], dtype=torch.long)
        # 타깃 위치 기준 마스크: 다음 토큰이 assistant 구간일 때 학습
        m = torch.tensor(mask_ids[1:], dtype=torch.long)
        return x, y, m

    def _build_mask(self, text: str) -> list[int]:
        """토큰별 1/0 마스크. assistant 응답 토큰만 1.

        재토큰화 정합성을 위해 조각별 인코딩 길이로 경계를 맞춘다.
        """
        spans = assistant_spans(text)
        mask: list[int] = []
        pos = 0
        cursor = 0
        for start, end in spans:
            # start 이전(비-assistant) 구간
            pre = text[cursor:start]
            mask += [0] * len(self.tok.encode(pre))
            # assistant 구간
            seg = text[start:end]
            mask += [1] * len(self.tok.encode(seg))
            cursor = end
        # 남은 꼬리
        tail = text[cursor:]
        mask += [0] * len(self.tok.encode(tail))
        return mask


# ---------------------------------------------------------------- 유틸

def collate(batch):
    xs, ys, ms = zip(*batch)
    return torch.stack(xs), torch.stack(ys), torch.stack(ms)


def iter_jsonl_text(path: str | Path) -> Iterator[str]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)["text"]
