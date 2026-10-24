"""Application signal ownership is scoped; services only handle cancellation."""

import asyncio
import signal
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest

from src.infrastructure.signals import ShutdownSignals


@pytest.mark.parametrize("outcome", ["normal", "failure", "cancellation"])
def test_signal_handlers_are_restored_after_every_outcome(outcome):
    loop = Mock()
    cancel = Mock()
    previous = {signal.SIGINT: signal.default_int_handler, signal.SIGTERM: signal.SIG_DFL}
    active = previous.copy()

    def install(signum, handler):
        old = active[signum]
        active[signum] = handler
        return old

    def scenario():
        with ShutdownSignals(loop, cancel) as handlers:
            assert active[signal.SIGINT] == handlers._handle
            assert active[signal.SIGTERM] == handlers._handle
            if outcome == "failure":
                raise RuntimeError("primary failure")
            if outcome == "cancellation":
                raise asyncio.CancelledError

    with (
        patch("src.infrastructure.signals.signal.getsignal", side_effect=active.get),
        patch("src.infrastructure.signals.signal.signal", side_effect=install),
    ):
        if outcome == "normal":
            scenario()
        elif outcome == "failure":
            with pytest.raises(RuntimeError, match="primary failure"):
                scenario()
        else:
            with pytest.raises(asyncio.CancelledError):
                scenario()
    assert active == previous
    cancel.assert_not_called()


def test_repeated_signals_schedule_only_one_cancellation():
    loop = Mock()
    cancel = Mock()
    with (
        patch("src.infrastructure.signals.signal.getsignal", return_value=signal.SIG_DFL),
        patch("src.infrastructure.signals.signal.signal"),
    ):
        with ShutdownSignals(loop, cancel) as handlers:
            handlers._handle(signal.SIGINT, None)
            handlers._handle(signal.SIGTERM, None)
            assert handlers.requested
            loop.call_soon_threadsafe.assert_called_once_with(cancel)
    cancel.assert_not_called()


def test_unsupported_registration_leaves_external_cancellation_available():
    loop = Mock()
    with (
        patch("src.infrastructure.signals.signal.getsignal", return_value=signal.SIG_DFL),
        patch("src.infrastructure.signals.signal.signal", side_effect=ValueError) as install,
    ):
        with pytest.raises(asyncio.CancelledError):
            with ShutdownSignals(loop, Mock()) as handlers:
                assert not handlers.requested
                raise asyncio.CancelledError
    assert install.call_count == 2
    loop.call_soon_threadsafe.assert_not_called()


def test_partial_registration_restores_only_installed_handlers():
    previous = signal.SIG_DFL
    with (
        patch("src.infrastructure.signals.signal.getsignal", return_value=previous),
        patch(
            "src.infrastructure.signals.signal.signal",
            side_effect=[previous, OSError("unsupported"), None],
        ) as install,
    ):
        with ShutdownSignals(Mock(), Mock()):
            pass
    assert install.call_args.args == (signal.SIGINT, previous)
    assert install.call_count == 3


def test_existing_host_handlers_and_ignored_signals_are_preserved():
    with (
        patch("src.infrastructure.signals.signal.getsignal", side_effect=[Mock(), signal.SIG_IGN]),
        patch("src.infrastructure.signals.signal.signal") as install,
    ):
        with ShutdownSignals(Mock(), Mock()):
            pass
    install.assert_not_called()


@pytest.mark.skipif(sys.platform == "win32", reason="loop-owned Unix signal callbacks")
def test_existing_loop_signal_callback_keeps_exclusive_ownership_in_subprocess():
    script = """
import asyncio
import os
import signal
from src.infrastructure.signals import ShutdownSignals

async def scenario():
    loop = asyncio.get_running_loop()
    received = asyncio.Event()
    cancellations = []
    loop.add_signal_handler(signal.SIGTERM, received.set)
    try:
        with ShutdownSignals(loop, lambda: cancellations.append(True)):
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.wait_for(received.wait(), 2)
            assert not cancellations
        received.clear()
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(received.wait(), 2)
        assert not cancellations
    finally:
        loop.remove_signal_handler(signal.SIGTERM)

asyncio.run(scenario())
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=5, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("has_primary", [True, False])
def test_restoration_attempts_all_handlers_and_preserves_primary_error(has_primary):
    cleanup = OSError("restore failed")
    primary = RuntimeError("primary failure")
    with (
        patch("src.infrastructure.signals.signal.getsignal", return_value=signal.SIG_DFL),
        patch(
            "src.infrastructure.signals.signal.signal", side_effect=[None, None, cleanup, None]
        ) as install,
    ):
        with pytest.raises(RuntimeError if has_primary else OSError) as caught:
            with ShutdownSignals(Mock(), Mock()):
                if has_primary:
                    raise primary
    assert caught.value is (primary if has_primary else cleanup)
    assert install.call_count == 4
