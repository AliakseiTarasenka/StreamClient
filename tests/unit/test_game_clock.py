"""Clock timing is deterministic and requires no live API or real overlay output."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.application.services.game_service import GameService
from src.domain.models.game_state import GameState


@pytest.mark.parametrize(
    ("stopped", "game_time", "expected"),
    [
        (True, 100, ["25:00", "24:50", "24:50", "24:50", "24:50"]),
        (False, 100, ["25:00", "24:49", "24:48", "24:45", "24:44"]),
        (False, 20000, ["25:00", "00:00", "00:00", "00:00", "00:00"]),
    ],
)
def test_clock_converts_tenths_counts_down_and_polls_at_five_second_boundaries(
    stopped, game_time, expected
):
    async def scenario():
        times = iter([100, 101, 101, 102, 105, 106])
        writer = SimpleNamespace(write_text=AsyncMock())
        service = GameService(SimpleNamespace(), writer)
        service.get_game_events = AsyncMock(
            return_value=GameState(
                12345,
                game_time=game_time,
                game_stopwatch_timestamp=1000,
                game_stopped=stopped,
            )
        )
        sleeps = 0

        async def advance(_delay):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 6:
                raise asyncio.CancelledError

        with (
            patch("src.application.services.game_service.time.time", side_effect=times),
            patch("src.application.services.game_service.asyncio.sleep", side_effect=advance),
        ):
            with pytest.raises(asyncio.CancelledError):
                await service.run_game_clock(12345, 25)
        assert [call.args for call in writer.write_text.await_args_list] == [
            ("clock.txt", value) for value in expected
        ]
        assert service.get_game_events.await_count == 2

    asyncio.run(scenario())
