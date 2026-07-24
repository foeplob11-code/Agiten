"""Agiten 토크나이저 — HuggingFace tokenizers 기반 BPE.

우리 코퍼스로 직접 학습한다(사전학습 가중치·기성 vocab 없음).
protocol.SPECIAL_TOKENS 는 절대 서브워드로 쪼개지지 않도록 special 로 등록한다.

의존: `pip install tokenizers`
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator

from .protocol import (
    SPECIAL_TOKENS, PAD, BOS, EOS,
    ASSISTANT, END,
)

_DEFAULT_PATH = "tokenizer.json"


class AgitenTokenizer:
    def __init__(self, backend):
        self._tk = backend
        self.pad_id = self.token_to_id(PAD)
        self.bos_id = self.token_to_id(BOS)
        self.eos_id = self.token_to_id(EOS)
        self.end_id = self.token_to_id(END)
        self.assistant_id = self.token_to_id(ASSISTANT)

    # ------------------------------------------------------------ 학습
    @classmethod
    def train(cls, texts: Iterable[str], vocab_size: int = 32768,
              min_frequency: int = 2) -> "AgitenTokenizer":
        from tokenizers import Tokenizer, models, trainers, pre_tokenizers, decoders

        tk = Tokenizer(models.BPE(unk_token=None))
        # ByteLevel: 어떤 바이트든 표현 가능 → UNK 없음, 한글/코드/이모지 안전
        tk.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
        tk.decoder = decoders.ByteLevel()

        trainer = trainers.BpeTrainer(
            vocab_size=vocab_size,
            min_frequency=min_frequency,
            special_tokens=SPECIAL_TOKENS,
            initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
            show_progress=True,
        )
        tk.train_from_iterator(_as_iter(texts), trainer=trainer)
        tk.add_special_tokens(SPECIAL_TOKENS)
        return cls(tk)

    # ------------------------------------------------------------ 입출력
    def save(self, path: str | Path = _DEFAULT_PATH) -> None:
        self._tk.save(str(path))

    @classmethod
    def load(cls, path: str | Path = _DEFAULT_PATH) -> "AgitenTokenizer":
        from tokenizers import Tokenizer
        return cls(Tokenizer.from_file(str(path)))

    # ------------------------------------------------------------ 인코딩
    def encode(self, text: str, add_bos: bool = False, add_eos: bool = False) -> list[int]:
        ids = self._tk.encode(text).ids
        if add_bos:
            ids = [self.bos_id] + ids
        if add_eos:
            ids = ids + [self.eos_id]
        return ids

    def decode(self, ids: list[int], skip_special: bool = False) -> str:
        return self._tk.decode(ids, skip_special_tokens=skip_special)

    def token_to_id(self, tok: str) -> int:
        return self._tk.token_to_id(tok)

    @property
    def vocab_size(self) -> int:
        return self._tk.get_vocab_size()


def _as_iter(texts: Iterable[str]) -> Iterator[str]:
    for t in texts:
        yield t


def iter_corpus_texts(paths: list[str | Path]) -> Iterator[str]:
    """jsonl 파일들에서 'text' 필드를 흘려보낸다(토크나이저 학습용).

    각 원소는 쉼표로 여러 경로를 담을 수 있다.
    """
    flat: list[str] = []
    for p in paths:
        flat.extend(s.strip() for s in str(p).split(",") if s.strip())
    for p in flat:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if "text" in obj:
                    yield obj["text"]
