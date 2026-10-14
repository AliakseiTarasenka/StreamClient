"""Lifecycle behavior is tested separately from CLI routing and infrastructure."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.application.services.live_session import LiveGameSession, ServiceLifecycle


@pytest.mark.parametrize("failed_index", [0, 1, 2])
def test_partial_startup_stops_attempted_services_and_awaits_created_tasks(failed_index):
    """Even the service whose start raises is stopped; later services never start."""

    async def scenario():
        initial_tasks = asyncio.all_tasks()
        scheduled = []
        error = RuntimeError("startup failed")

        async def start_running(*_args):
            task = asyncio.create_task(asyncio.Event().wait())
            scheduled.append(task)
            return task

        services = [
            ServiceLifecycle(
                f"service-{index}",
                AsyncMock(side_effect=error if index == failed_index else start_running),
                AsyncMock(),
            )
            for index in range(3)
        ]
        session = LiveGameSession(services)
        try:
            with pytest.raises(RuntimeError) as caught:
                await session.run(12345, 25)
            assert caught.value is error
            assert len(scheduled) == failed_index
            assert all(task.done() and task.cancelled() for task in scheduled)
            for index, service in enumerate(services):
                if index <= failed_index:
                    service.start.assert_awaited_once_with(12345, 25)
                    service.stop.assert_awaited_once_with(12345)
                else:
                    service.start.assert_not_awaited()
                    service.stop.assert_not_awaited()
            assert asyncio.all_tasks() <= initial_tasks
        finally:
            for task in scheduled:
                task.cancel()
            await asyncio.gather(*scheduled, return_exceptions=True)

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


def test_synchronous_stop_adapter_failure_does_not_skip_other_cleanup():
    """A callable adapter can fail before returning an awaitable."""

    async def scenario():
        error = RuntimeError("stop adapter failed")

        def fail_before_await(_game_id):
            raise error

        async def start(*_args):
            return asyncio.create_task(asyncio.sleep(0))

        healthy_stop = AsyncMock()
        services = [
            ServiceLifecycle("broken", start, fail_before_await),
            ServiceLifecycle("healthy", start, healthy_stop),
        ]
        session = LiveGameSession(services, report_error=lambda _message: None)
        with pytest.raises(RuntimeError) as caught:
            await session.run(12345, 25)
        assert caught.value is error
        healthy_stop.assert_awaited_once_with(12345)

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


@pytest.mark.parametrize("outcome", ["normal", "failure", "cancellation"])
def test_cleanup_attempts_every_stop_and_preserves_the_primary_outcome(outcome):
    """All cleanup finishes, even when one stop fails during a runtime failure or cancellation."""

    async def scenario():
        initial_tasks = asyncio.all_tasks()
        started = [asyncio.Event(), asyncio.Event()]
        finished = [asyncio.Event(), asyncio.Event()]
        primary_error = RuntimeError("runtime failed")
        cleanup_error = RuntimeError("cleanup failed")
        messages = []

        def starter(index):
            async def run_loop():
                started[index].set()
                try:
                    await asyncio.gather(*(event.wait() for event in started))
                    if index == 0 and outcome == "failure":
                        raise primary_error
                    if index == 0 and outcome == "normal":
                        return
                    await asyncio.Event().wait()
                finally:
                    finished[index].set()

            async def start(*_args):
                return asyncio.create_task(run_loop())

            return start

        services = [
            ServiceLifecycle("first", starter(0), AsyncMock(side_effect=cleanup_error)),
            ServiceLifecycle("second", starter(1), AsyncMock()),
        ]
        session = LiveGameSession(services, report_error=messages.append)
        task = asyncio.create_task(session.run(12345, 25))
        try:
            await asyncio.gather(*(event.wait() for event in started))
            if outcome == "cancellation":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(RuntimeError) as caught:
                    await task
                assert caught.value is (primary_error if outcome == "failure" else cleanup_error)
            assert all(event.is_set() for event in finished)
            for service in services:
                service.stop.assert_awaited_once_with(12345)
            assert messages == ["Error stopping first: cleanup failed"]
            assert asyncio.all_tasks() <= initial_tasks
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))
