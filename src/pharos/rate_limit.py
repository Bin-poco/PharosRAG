"""进程内、按 API key 隔离的令牌桶；不保存明文 key。"""
from __future__ import annotations

import hashlib
import math
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class KeyRateLimiter:
    def __init__(self, rate: float, burst: int, *, clock: Callable[[], float] = time.monotonic):
        if not math.isfinite(rate) or rate <= 0 or burst < 1:
            raise ValueError("rate 必须大于 0，burst 必须至少为 1")
        self.rate = rate
        self.burst = burst
        self._clock = clock
        self._salt = secrets.token_bytes(32)
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def allow(self, api_key: str) -> tuple[bool, int]:
        """返回 (是否放行, 再试等待秒数)。调用方必须先完成鉴权。"""
        fingerprint = hashlib.sha256(self._salt + api_key.encode("utf-8")).hexdigest()
        with self._lock:
            now = self._clock()
            bucket = self._buckets.get(fingerprint)
            if bucket is None:
                bucket = _Bucket(float(self.burst), now)
                self._buckets[fingerprint] = bucket
            bucket.tokens = min(float(self.burst), bucket.tokens + max(0.0, now - bucket.updated_at) * self.rate)
            bucket.updated_at = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True, 0
            return False, max(1, math.ceil((1.0 - bucket.tokens) / self.rate))
