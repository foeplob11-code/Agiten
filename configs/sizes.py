"""모델 크기 프리셋. 코드는 그대로, 이 값만 바꿔 스케일업한다.

n_params 는 model.ModelConfig.n_params() 와 일치한다(임베딩 공유 기준).
Colab 열은 대략적인 실행 가능성 메모.
"""

from agiten.model import ModelConfig

# vocab 은 토크나이저 학습 후 실제값으로 덮어쓴다(build 시 자동).
PRESETS: dict[str, dict] = {
    # ~30M — 파이프라인 검증용. T4에서 몇 시간이면 한 바퀴.
    "smoke": dict(dim=384, n_layers=6, n_heads=6, n_kv_heads=2,
                  ffn_dim=1024, max_seq_len=1024),

    # ~120M — 실사용 최소선. T4 무료로 하루 안쪽에 의미 있는 결과.
    "base": dict(dim=768, n_layers=12, n_heads=12, n_kv_heads=4,
                 ffn_dim=2048, max_seq_len=2048),

    # ~350M — A100/L4 권장.
    "large": dict(dim=1024, n_layers=24, n_heads=16, n_kv_heads=4,
                  ffn_dim=2816, max_seq_len=2048),

    # ~1.5B — 목표. A100 40GB+ 필요. 코드 변경 없이 이 프리셋만 선택.
    "xl": dict(dim=2048, n_layers=30, n_heads=16, n_kv_heads=8,
               ffn_dim=6144, max_seq_len=2048),
}


def make_config(preset: str, vocab_size: int) -> ModelConfig:
    if preset not in PRESETS:
        raise KeyError(f"알 수 없는 프리셋: {preset}. 선택지: {list(PRESETS)}")
    return ModelConfig(vocab_size=vocab_size, **PRESETS[preset])


if __name__ == "__main__":
    for name in PRESETS:
        cfg = make_config(name, vocab_size=32768)
        print(f"{name:6s}  {cfg.n_params()/1e6:8.1f}M params  "
              f"dim={cfg.dim} L={cfg.n_layers} H={cfg.n_heads}")
