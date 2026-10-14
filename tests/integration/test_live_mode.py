"""Live-mode supervision tests using the real clock and polling service classes."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from config.settings import Settings
from main import create_live_session
from src.application.services.game_service import GameService
from src.domain.models.game_state import GameState
from src.infrastructure.persistence.async_file_manager import AsyncFileManager
from src.infrastructure.websocket.server import WebSocketGameServer


async def cancel_task(task):
    """Always clean up probes, including when an assertion fails."""
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def test_file_only_mode_keeps_polling_and_updates_overlay_files(tmp_path):
    """The actual clock and polling loops stay alive through multiple snapshots."""

    async def scenario():
        initial_tasks = asyncio.all_tasks()
        third_snapshot = asyncio.Event()
        requests = 0

        async def response(_data, **_kwargs):
            nonlocal requests
            requests += 1
            if requests > 3:
                # The preceding snapshot has completed its file writes.
                third_snapshot.set()
                await asyncio.Event().wait()
            return json.dumps({"game_id": 12345, "h": requests, "a": 0})

        api = SimpleNamespace(post=response)
        service = GameService(api, AsyncFileManager(tmp_path))
        service.get_game_events = AsyncMock(return_value=GameState(12345))
        settings = Settings(_env_file=None, poll_interval=0)
        session = create_live_session(service, service.file_writer, settings.poll_interval, None)
        task = asyncio.create_task(session.run(12345, 25))
        try:
            await third_snapshot.wait()
            assert not task.done()
            assert (tmp_path / "home_score.txt").read_text() == "3"
            assert (tmp_path / "away_score.txt").read_text() == "0"
            assert (tmp_path / "clock.txt").exists()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert asyncio.all_tasks() <= initial_tasks
        finally:
            await cancel_task(task)

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


@pytest.mark.parametrize(
    ("failure_source", "enable_websocket"),
    [("clock", False), ("clock", True), ("polling", False), ("polling", True), ("websocket", True)],
)
def test_service_failure_stops_siblings_and_propagates(failure_source, enable_websocket):
    """A clock, exhausted poll, or server failure terminates the live session."""

    async def scenario():
        initial_tasks = asyncio.all_tasks()
        clock_started = asyncio.Event()
        polling_started = asyncio.Event()
        websocket_started = asyncio.Event()
        clock_stopped = asyncio.Event()
        polling_stopped = asyncio.Event()
        websocket_stopped = asyncio.Event()
        error = RuntimeError(f"{failure_source} failed")
        poll_attempts = 0

        async def ready():
            await clock_started.wait()
            await polling_started.wait()
            if enable_websocket:
                await websocket_started.wait()

        async def run_clock(*_args):
            clock_started.set()
            try:
                await ready()
                if failure_source == "clock":
                    raise error
                await asyncio.Event().wait()
            finally:
                clock_stopped.set()

        async def fetch(*_args):
            nonlocal poll_attempts
            polling_started.set()
            try:
                await ready()
                if failure_source == "polling":
                    poll_attempts += 1
                    raise error
                await asyncio.Event().wait()
            finally:
                polling_stopped.set()

        async def serve():
            websocket_started.set()
            try:
                await ready()
                if failure_source == "websocket":
                    raise error
                await asyncio.Event().wait()
            finally:
                websocket_stopped.set()

        websocket = (
            SimpleNamespace(start=serve, stop=AsyncMock(), broadcast_game_update=AsyncMock())
            if enable_websocket
            else None
        )
        service = SimpleNamespace(
            file_writer=object(),
            run_game_clock=run_clock,
            get_game_events=fetch,
            get_game_events_with_persistence=fetch,
        )
        session = create_live_session(service, service.file_writer, 0, websocket)
        with pytest.raises(RuntimeError) as caught:
            await session.run(12345, 25)
        assert caught.value is error
        assert clock_stopped.is_set()
        assert polling_stopped.is_set()
        if websocket:
            assert websocket_stopped.is_set()
            websocket.stop.assert_awaited_once()
        if failure_source == "polling":
            assert poll_attempts == 5
        assert asyncio.all_tasks() <= initial_tasks

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


def test_normal_websocket_shutdown_stops_clock_and_polling():
    """A real server shutdown ends the session even though its sibling loops run forever."""

    async def scenario():
        initial_tasks = asyncio.all_tasks()
        clock_started = asyncio.Event()
        polling_started = asyncio.Event()
        clock_stopped = asyncio.Event()
        polling_stopped = asyncio.Event()

        async def clock(*_args):
            clock_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                clock_stopped.set()

        async def fetch(*_args):
            polling_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                polling_stopped.set()

        websocket = WebSocketGameServer("127.0.0.1", 0)
        service = SimpleNamespace(file_writer=object(), run_game_clock=clock, get_game_events=fetch)
        session = create_live_session(service, service.file_writer, 2, websocket)
        loop = asyncio.get_running_loop()
        # Capture the registered shutdown callback without replacing process signal handlers.
        with patch.object(loop, "add_signal_handler") as register:
            task = asyncio.create_task(session.run(12345, 25))
            try:
                await clock_started.wait()
                await polling_started.wait()
                # start() registers handlers after binding the socket; wait for registration.
                while not register.called:
                    await asyncio.sleep(0)
                register.call_args.args[1]()
                await task
                assert clock_stopped.is_set()
                assert polling_stopped.is_set()
                assert not websocket._running
                assert not websocket._server.is_serving()
                assert asyncio.all_tasks() <= initial_tasks
            finally:
                await cancel_task(task)

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))
