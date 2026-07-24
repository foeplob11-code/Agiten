# Agiten

처음부터(from scratch) 직접 학습하는 에이전트형 개인비서. 사전학습된 남의 모델을
쓰지 않고, 아키텍처·토크나이저·데이터를 전부 직접 만든다. 터미널, 파일/코드,
이메일, 메신저, 일정, 기억을 도구로 다루도록 학습한다.

## 핵심 설계

- **모델**: 순수 PyTorch 디코더 트랜스포머 (RMSNorm + RoPE + GQA + SwiGLU, 임베딩 공유).
  크기는 `configs/sizes.py` 프리셋만 바꾸면 됨. 코드는 그대로.
- **토크나이저**: 우리 코퍼스로 직접 학습한 ByteLevel BPE. 특수 토큰은 절대 쪼개지지 않음.
- **프로토콜**: 학습과 추론이 **동일한** 렌더러(`agiten/protocol.py`)를 공유 →
  학습 포맷과 추론 포맷이 어긋날 수 없음.
- **안전**: 되돌릴 수 없는 도구(`fs.write`, `email.send`, `chat.send`, `cal.create` …)는
  실행 전 사용자 확인을 받도록 데이터에 각인.

## 크기 프리셋

```
smoke   10.4M  — 파이프라인 검증 (T4 몇 시간)
base   ~120M  — T4 무료 권장 시작점
large  ~350M  — L4 / A100
xl      ~1.5B  — 목표. A100 40GB+ 필요 (프리셋만 xl 로 바꾸면 됨)
```

> **1.5B 를 처음부터 사전학습하는 비용**: Chinchilla 기준 ~30B 토큰 필요 →
> T4 한 장으로는 수개월. 그래서 이 저장소는 `smoke→base` 로 파이프라인을 검증하고,
> GPU 예산이 생기면 `xl` 프리셋으로 그대로 확장하도록 설계했다.

## 빠른 시작 (로컬)

```bash
pip install -r requirements.txt

# 1) 기초 데이터 생성
python -m agiten.datagen.build --n 40000 --corpus-n 12000 --out data/processed

# 2) 토크나이저 학습
python scripts/train_tokenizer.py --vocab-size 32768 --out tokenizer.json

# 3) 프리트레인 (언어 습득)
python scripts/train.py --stage pretrain --preset base \
    --data data/processed/corpus.jsonl --out runs/base-pt \
    --steps 20000 --resume --grad-ckpt

# 4) SFT (에이전트 행동)
python scripts/train.py --stage sft --preset base \
    --data data/processed/sft.jsonl --val data/processed/sft_val.jsonl \
    --init runs/base-pt/ckpt_last.pt --out runs/base-sft \
    --steps 6000 --resume --grad-ckpt

# 5) 대화
python scripts/chat.py --ckpt runs/base-sft/ckpt_last.pt --interactive
```

## Colab (학습만 켜놓으면 됨) — Hugging Face 저장, 드라이브 불필요

`notebooks/Agiten_Colab.ipynb` 를 Colab 에서 열고 위에서부터 실행.
체크포인트·토크나이저는 **Hugging Face Hub** 에 저장된다(구글 드라이브 안 씀).
`--hf-repo` + `--resume` 덕분에 **런타임이 끊겨도 셀을 다시 실행하면
Hub 에서 내려받아 이어서 학습**한다.

- 준비물: 무료 HF 계정 + 쓰기 토큰 (https://huggingface.co/settings/tokens)
- 데이터는 저장 안 함 — 매 세션 재생성(합성은 시드 고정으로 동일, 실제 코퍼스는 Hub 캐시)
- 저장되는 것: `tokenizer.json`, `corpus_real.jsonl`, `<run>/ckpt_last.pt`

로컬에서도 `--hf-repo hobak/agiten-ckpts` 를 붙이면 동일하게 동작한다
(토큰은 환경변수 `HF_TOKEN`).

## 구조

```
agiten/
  protocol.py      대화/툴콜 포맷 + 손실 마스킹 (학습·추론 공용)
  toolspec.py      도구 카탈로그 (확인필요 여부 포함)
  model.py         트랜스포머 본체 + KV캐시 생성
  tokenizer.py     ByteLevel BPE 학습/로드
  data.py          패킹(프리트레인) / SFT 마스킹 데이터셋
  datagen/         합성 데이터 생성기
configs/sizes.py   크기 프리셋
scripts/           train_tokenizer · train · chat
notebooks/         Colab 원클릭 노트북
```

## 지금 데이터의 한계와 다음 단계

현재 `기초 데이터`는 템플릿 합성이라 **고유 첫 발화가 ~200종**으로 다양성이 낮다.
파이프라인 검증·부트스트랩엔 충분하지만, 진지한 학습 전에 다음을 권장:

1. `agiten/datagen/generators.py` 의 슬롯 값·템플릿·시나리오 확장
2. 실제 프리트레인 코퍼스 연결(공개 한국어/코드 코퍼스) — `corpus.jsonl` 에 합류
3. 실제 도구 실행 로그를 수집해 SFT 에 추가(온-폴리시 데이터)
```
