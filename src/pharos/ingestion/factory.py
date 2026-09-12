"""HTTP 进程与 Worker 共用的摄取依赖装配。"""
from __future__ import annotations

import os

from ..mineru import MinerUClient


def build_mineru_client(cfg) -> MinerUClient:
    token_names = list(dict.fromkeys([
        cfg.mineru_token_env, "MINERU_TOKEN", "MINERU_TOKEN_A",
        "MINERU_TOKEN_B", "MINERU_TOKEN_C",
    ]))
    token = next((os.environ.get(name, "").strip() for name in token_names
                  if name and os.environ.get(name, "").strip()), "")
    return MinerUClient(
        token=token,
        base_url=cfg.mineru_base_url,
        model_version=cfg.mineru_model_version,
        language=cfg.mineru_language,
        poll_seconds=cfg.mineru_poll_seconds,
        timeout_seconds=cfg.mineru_timeout_seconds,
        max_archive_bytes=cfg.mineru_max_archive_bytes,
    )
