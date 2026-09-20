"""Request deadlines with bounded blocking work and context-local network budgets.

Python cannot safely kill a running thread (nor cancel computation already accepted
by a provider). Stop waiting at the deadline, discard late results, and keep the
slot occupied until that call exits. Adapters also bound their I/O and retries.
"""
from __future__ import annotations

import contextvars
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout


class DeadlineExceeded(TimeoutError):
    pass


_CURRENT = contextvars.ContextVar("rag_deadline", default=None)
_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="rag-deadline")
_SLOTS = threading.BoundedSemaphore(16)


class Deadline:
    def __init__(self, seconds: float):
        self.ends_at = time.monotonic() + max(0.0, seconds)

    def remaining(self) -> float:
        value = self.ends_at - time.monotonic()
        if value <= 0:
            raise DeadlineExceeded("request_deadline_exceeded")
        return value

    def call(self, fn):
        # No unbounded executor queue, even when upstream calls ignore cancellation.
        slots = _SLOTS
        if not slots.acquire(timeout=self.remaining()):
            raise DeadlineExceeded("request_deadline_exceeded")
        context = contextvars.copy_context()

        def invoke():
            token = _CURRENT.set(self)
            try:
                self.remaining()
                result = fn()
                self.remaining()
                return result
            finally:
                _CURRENT.reset(token)

        try:
            future = _POOL.submit(context.run, invoke)
        except BaseException:
            slots.release()
            raise
        future.add_done_callback(lambda _: slots.release())
        try:
            result = future.result(timeout=self.remaining())
            self.remaining()
            return result
        except FutureTimeout:
            if future.done():
                # Preserve an upstream timeout that occurred before our deadline.
                self.remaining()
                return future.result()
            future.cancel()
            raise DeadlineExceeded("request_deadline_exceeded") from None


def remaining_seconds() -> float | None:
    deadline = _CURRENT.get()
    return deadline.remaining() if deadline is not None else None


def check_deadline() -> None:
    remaining_seconds()


def retry_sleep(seconds: float) -> None:
    remaining = remaining_seconds()
    time.sleep(max(0.0, min(seconds, remaining) if remaining is not None else seconds))
    check_deadline()
