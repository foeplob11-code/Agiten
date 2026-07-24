"""Hugging Face Hub 체크포인트 동기화.

구글 드라이브 대신 HF 저장소에 체크포인트/토크나이저를 보관한다.
학습 중 주기적으로 업로드 → Colab 이 끊겨도, 다음 세션에서 내려받아 이어서 학습.

토큰: 인자 token 우선, 없으면 환경변수 HF_TOKEN.
모든 네트워크 작업은 실패해도 학습을 죽이지 않도록 감싼다(경고만).
의존: pip install huggingface_hub
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _token(token: str | None) -> str | None:
    return token or os.environ.get("HF_TOKEN")


def enabled(repo_id: str | None) -> bool:
    return bool(repo_id)


def ensure_repo(repo_id: str, token: str | None = None, private: bool = True) -> bool:
    try:
        from huggingface_hub import create_repo
        create_repo(repo_id, token=_token(token), private=private,
                    exist_ok=True, repo_type="model")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[hub] 저장소 준비 실패(무시): {e}")
        return False


def download(repo_id: str, path_in_repo: str, local_path: str | Path,
             token: str | None = None) -> bool:
    """저장소의 파일을 local_path 로 내려받는다. 없으면 False."""
    try:
        from huggingface_hub import hf_hub_download
        f = hf_hub_download(repo_id, path_in_repo, repo_type="model", token=_token(token))
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(f, local_path)
        print(f"[hub] 내려받음: {path_in_repo} -> {local_path}")
        return True
    except Exception as e:  # noqa: BLE001 — EntryNotFound 등
        print(f"[hub] 내려받기 없음/실패: {path_in_repo} ({type(e).__name__})")
        return False


def upload(repo_id: str, local_path: str | Path, path_in_repo: str,
           token: str | None = None) -> bool:
    """local_path 를 저장소 path_in_repo 로 올린다(덮어씀)."""
    try:
        from huggingface_hub import HfApi
        HfApi(token=_token(token)).upload_file(
            path_or_fileobj=str(local_path),
            path_in_repo=path_in_repo,
            repo_id=repo_id,
            repo_type="model",
        )
        print(f"[hub] 업로드: {local_path} -> {path_in_repo}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[hub] 업로드 실패(무시하고 계속): {e}")
        return False


def repo_path_for(out_dir: str | Path, filename: str = "ckpt_last.pt") -> str:
    """out 디렉토리 이름을 저장소 내 경로 접두사로 쓴다. 예: runs/base-pt -> base-pt/ckpt_last.pt"""
    return f"{Path(out_dir).name}/{filename}"
