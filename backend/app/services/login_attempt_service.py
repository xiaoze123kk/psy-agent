from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MAX_FAILURES_PER_IP = 10
MAX_FAILURES_PER_USERNAME = 5
BLOCK_WINDOW_SECONDS = 300


@dataclass
class _Bucket:
    failures: int = 0
    first_failure_at: float = 0.0


@dataclass
class LoginAttemptStore:
    _by_ip: dict[str, _Bucket] = field(default_factory=dict)
    _by_username: dict[str, _Bucket] = field(default_factory=dict)

    def _cleanup_bucket(self, bucket: _Bucket) -> bool:
        if time.monotonic() - bucket.first_failure_at > BLOCK_WINDOW_SECONDS:
            return True
        return False

    def record_failure(self, ip: str, username: str, reason: str) -> None:
        now = time.monotonic()
        for store, key in [(self._by_ip, ip), (self._by_username, username)]:
            bucket = store.get(key)
            if bucket is None or self._cleanup_bucket(bucket):
                store[key] = _Bucket(failures=1, first_failure_at=now)
            else:
                bucket.failures += 1
        logger.warning("login_failed ip=%s user=%s reason=%s", ip, username, reason)

    def is_blocked(self, ip: str, username: str) -> tuple[bool, str | None]:
        now = time.monotonic()
        for store, key, label in [
            (self._by_ip, ip, "ip"),
            (self._by_username, username, "username"),
        ]:
            bucket = store.get(key)
            if bucket is not None and not self._cleanup_bucket(bucket):
                limit = MAX_FAILURES_PER_IP if label == "ip" else MAX_FAILURES_PER_USERNAME
                if bucket.failures >= limit:
                    remaining = int(BLOCK_WINDOW_SECONDS - (now - bucket.first_failure_at))
                    return True, f"登录尝试次数过多，请在 {remaining} 秒后重试。"
        return False, None

    def clear(self, ip: str, username: str) -> None:
        self._by_ip.pop(ip, None)
        self._by_username.pop(username, None)


login_attempt_store = LoginAttemptStore()
