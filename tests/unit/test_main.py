"""Resource ownership at the composition root."""

import asyncio
import signal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import main
from config.settings import Settings


def test_dependency_construction_failure_closes_api_client(tmp_path):
    """Even a wiring failure happens inside the API client's protected lifetime."""

    async def scenario():
        client = SimpleNamespace(close=AsyncMock())
        error = RuntimeError("composition failed")
        with (
            patch(
                "main.Settings", return_value=Settings(_env_file=None, output_path=str(tmp_path))
            ),
            patch("main.APIClientPool", return_value=client),
            patch("main.create_live_session", side_effect=error),
        ):
            with pytest.raises(RuntimeError) as caught:
                await main.main()
        assert caught.value is error
        client.close.assert_awaited_once()

    asyncio.run(scenario())


def test_configured_request_timeout_is_passed_to_http_client(tmp_path):
    async def scenario():
        client = SimpleNamespace(close=AsyncMock())
        cli = SimpleNamespace(handle=AsyncMock())
        settings = Settings(_env_file=None, output_path=str(tmp_path), request_timeout=7)
        with (
            patch("main.Settings", return_value=settings),
            patch("main.APIClientPool", return_value=client) as construct_client,
            patch("main.CLIHandler", return_value=cli),
        ):
            await main.main()
        assert construct_client.call_args.kwargs["timeout"] == 7
        cli.handle.assert_awaited_once()
        client.close.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize("shutdown", ["signal", "external", "unsupported"])
def test_application_cancellation_releases_resources_and_restores_signal_handlers(shutdown):
    async def scenario():
        baseline = asyncio.all_tasks()
        started = asyncio.Event()
        closed = asyncio.Event()
        previous = {signal.SIGINT: signal.SIG_DFL, signal.SIGTERM: signal.SIG_DFL}
        active = previous.copy()

        def install(signum, callback):
            if shutdown == "unsupported":
                raise ValueError("not the main thread")
            old = active[signum]
            active[signum] = callback
            return old

        async def run():
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                closed.set()

        with (
            patch("main.run_application", side_effect=run),
            patch("src.infrastructure.signals.signal.getsignal", side_effect=active.get),
            patch("src.infrastructure.signals.signal.signal", side_effect=install),
        ):
            task = asyncio.create_task(main.main())
            try:
                await started.wait()
                if shutdown == "signal":
                    active[signal.SIGTERM](signal.SIGTERM, None)
                    await task
                else:
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert closed.is_set()
        assert active == previous
        assert asyncio.all_tasks() <= baseline

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


@pytest.mark.parametrize("outcome", ["normal", "failure", "cancellation"])
def test_http_cleanup_error_preserves_primary_outcome(tmp_path, outcome):
    async def scenario():
        cleanup = OSError("close failed")
        primary = (
            asyncio.CancelledError() if outcome == "cancellation" else RuntimeError("CLI failed")
        )
        client = SimpleNamespace(close=AsyncMock(side_effect=cleanup))
        cli = SimpleNamespace(
            handle=AsyncMock(side_effect=primary if outcome != "normal" else None)
        )
        with (
            patch(
                "main.Settings", return_value=Settings(_env_file=None, output_path=str(tmp_path))
            ),
            patch("main.APIClientPool", return_value=client),
            patch("main.CLIHandler", return_value=cli),
        ):
            expected = cleanup if outcome == "normal" else primary
            with pytest.raises(type(expected)) as caught:
                await main.run_application()
        assert caught.value is expected
        client.close.assert_awaited_once()

    asyncio.run(scenario())
