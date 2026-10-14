"""Command routing and output tests with injected application interfaces."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config.settings import Settings
from src.domain.models.game_state import GameState
from src.presentation.cli import CLIHandler


@pytest.mark.parametrize(
    ("arguments", "operation"),
    [
        (["--date", "2025-10-05"], "schedule"),
        (["--game", "12345"], "game"),
        (["--game", "12345", "--start"], "live"),
        (["--game", "12345", "--date", "2025-10-05"], "game"),
    ],
)
def test_command_routes_to_the_injected_application_interface(arguments, operation):
    """Queries and live commands invoke only the application operation they need."""

    async def scenario():
        messages = []
        state = GameState(12345)
        queries = SimpleNamespace(
            get_game_schedule=AsyncMock(return_value="schedule result"),
            get_game_events_with_persistence=AsyncMock(return_value=state),
        )
        session = SimpleNamespace(run=AsyncMock())
        settings = Settings(_env_file=None, game_duration=31)
        handler = CLIHandler(queries, session, settings, output=messages.append)
        await handler.handle(arguments)

        if operation == "schedule":
            queries.get_game_schedule.assert_awaited_once_with("2025-10-05")
            queries.get_game_events_with_persistence.assert_not_awaited()
            session.run.assert_not_awaited()
            assert messages[-1] == "schedule result"
        elif operation == "game":
            queries.get_game_events_with_persistence.assert_awaited_once_with(12345)
            queries.get_game_schedule.assert_not_awaited()
            session.run.assert_not_awaited()
            assert messages[-1] == str(state)
        else:
            session.run.assert_awaited_once_with(12345, 31)
            queries.get_game_schedule.assert_not_awaited()
            queries.get_game_events_with_persistence.assert_not_awaited()
            assert messages[-1] == "Shutdown complete."

    asyncio.run(scenario())


def test_missing_command_reports_error_without_starting_services():
    """Argument errors don't invoke application operations."""

    async def scenario():
        queries = SimpleNamespace(
            get_game_schedule=AsyncMock(), get_game_events_with_persistence=AsyncMock()
        )
        session = SimpleNamespace(run=AsyncMock())
        messages = []
        handler = CLIHandler(queries, session, Settings(_env_file=None), output=messages.append)
        await handler.handle([])
        assert messages[-1] == "Error: Please specify either --game or --date"
        queries.get_game_schedule.assert_not_awaited()
        queries.get_game_events_with_persistence.assert_not_awaited()
        session.run.assert_not_awaited()

    asyncio.run(scenario())


def test_live_failure_is_displayed_and_propagated():
    """The presentation reports a session failure without claiming successful shutdown."""

    async def scenario():
        error = RuntimeError("clock failed")
        session = SimpleNamespace(run=AsyncMock(side_effect=error))
        messages = []
        handler = CLIHandler(
            SimpleNamespace(), session, Settings(_env_file=None), output=messages.append
        )
        with pytest.raises(RuntimeError) as caught:
            await handler.handle(["--game", "12345", "--start"])
        assert caught.value is error
        assert messages[-1] == "Error: clock failed"
        assert "Shutdown complete." not in messages

    asyncio.run(scenario())


def test_cli_propagates_session_cancellation():
    """Cancellation remains visible to asyncio.run and its signal handling."""

    async def scenario():
        session = SimpleNamespace(run=AsyncMock(side_effect=asyncio.CancelledError))
        handler = CLIHandler(
            SimpleNamespace(), session, Settings(_env_file=None), output=lambda _message: None
        )
        with pytest.raises(asyncio.CancelledError):
            await handler.handle(["--game", "12345", "--start"])

    asyncio.run(scenario())
