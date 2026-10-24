"""Scoped process signals for the application's cancellation boundary."""

import asyncio
import signal
from collections.abc import Callable
from types import FrameType
from typing import Any


class ShutdownSignals:
    """Request cancellation once and restore every process handler we replace.

    Use process handlers so main-thread Windows loops need no add_signal_handler
    support. Existing custom/ignored handlers belong to the host and are retained,
    including asyncio.Runner's SIGINT cancellation and loop-owned signal callbacks.
    Non-main-thread callers retain ordinary external task cancellation.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, cancel: Callable[[], object]):
        self._loop = loop
        self._cancel = cancel
        self._previous: dict[signal.Signals, Any] = {}
        self.requested = False

    def __enter__(self) -> "ShutdownSignals":
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                previous = signal.getsignal(signum)
                if previous not in (signal.SIG_DFL, signal.default_int_handler):
                    continue
                signal.signal(signum, self._handle)
            except (ValueError, OSError, RuntimeError):
                # Python only allows signal registration in the main thread.
                continue
            self._previous[signum] = previous
        return self

    def _handle(self, _signum: int, _frame: FrameType | None) -> None:
        if not self.requested:
            self.requested = True
            # Signal callbacks must not perform service shutdown themselves.
            self._loop.call_soon_threadsafe(self._cancel)

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        errors = []
        for signum, previous in self._previous.items():
            try:
                signal.signal(signum, previous)
            except (ValueError, OSError, RuntimeError) as error:
                errors.append(error)
                print(f"Error restoring signal {signum.name}: {error}")
        self._previous.clear()
        if _exc_value is None and errors:
            raise errors[0]
