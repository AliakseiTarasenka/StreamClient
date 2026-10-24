"""HTTP-to-overlay regressions using deterministic upstream responses."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest

from src.application.commands.process_game import ProcessGameEventsWithPersistence
from src.application.services.game_service import GameService
from src.infrastructure.api.client import APIClientPool
from src.infrastructure.persistence.async_file_manager import AsyncFileManager
from src.infrastructure.websocket.streamer import GameEventStreamer


SCORING_RESPONSE = {
    "game_id": 12345,
    "h": 0,
    "a": 0,
    "hn": "Home Team",
    "ha": "HOME",
    "an": "Away Team",
    "aa": "AWAY",
    "p": {"h": {"7": "Alex", "9": "Sam"}, "a": {"3": "Robin"}},
    "e": [{"t": 120, "e": "h", "y": "S", "s": 7, "a": 9, "hs": 1, "as": 0}],
}

EXPECTED_OVERLAYS = {
    "home_roster.txt": "7: Alex\n9: Sam\n",
    "away_roster.txt": "3: Robin\n",
    "home_name.txt": "HOME",
    "away_name.txt": "AWAY",
    "home_name_full.txt": "Home Team",
    "away_name_full.txt": "Away Team",
    "home_score.txt": "1",
    "away_score.txt": "0",
    "scorer.txt": "Alex",
    "assist.txt": "Sam",
}


@pytest.mark.parametrize("mode", ["query", "file", "websocket"])
def test_scoring_response_persists_all_overlays_with_one_fetch(tmp_path, mode):
    """Query and both monitoring modes share the same parsed-snapshot persistence."""

    async def scenario():
        requests = []

        def upstream(request):
            requests.append(parse_qs(request.content.decode()))
            return httpx.Response(200, json=SCORING_RESPONSE)

        async with APIClientPool(
            "https://scores.example/events", transport=httpx.MockTransport(upstream)
        ) as api:
            service = GameService(api, AsyncFileManager(tmp_path))
            if mode == "query":
                state = await service.get_game_events_with_persistence(12345)
                assert state.latest_scorer == "Alex"
                assert len(state.events) == 1
            else:
                completed = asyncio.Event()
                persist = service.persist_game_state

                async def save(state):
                    await persist(state)
                    if mode == "file":
                        completed.set()

                async def publish(game_id, state):
                    assert game_id == 12345
                    assert state["events"][0]["scorer"] == "Alex"
                    json.dumps(state)
                    completed.set()

                service.persist_game_state = save
                publisher = (
                    SimpleNamespace(broadcast_game_update=AsyncMock(side_effect=publish))
                    if mode == "websocket"
                    else None
                )
                streamer = GameEventStreamer(service, 60, publisher)
                task = await streamer.start_monitoring(12345)
                try:
                    await completed.wait()
                    assert not task.done()
                finally:
                    await streamer.stop_all()
                assert task.cancelled()

            assert requests == [
                {"game": ["12345"], "update": ["true"], "players": ["true"], "teams": ["true"]}
            ]
            assert {path.name: path.read_text() for path in tmp_path.iterdir()} == EXPECTED_OVERLAYS

    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_explicit_snapshot_persistence_never_fetches_again(tmp_path):
    """Callers can save a previously fetched snapshot even after HTTP has closed."""

    async def scenario():
        api = SimpleNamespace(post=AsyncMock(return_value=json.dumps(SCORING_RESPONSE)))
        service = GameService(api, AsyncFileManager(tmp_path))
        state = await service.get_game_events(12345)
        api.post.side_effect = AssertionError("persistence must not fetch")
        await service.persist_game_state(state)
        api.post.assert_awaited_once()
        assert {path.name: path.read_text() for path in tmp_path.iterdir()} == EXPECTED_OVERLAYS

    asyncio.run(scenario())


def test_persistence_command_uses_shared_snapshot_mapping(tmp_path):
    """The existing persistence command retains the same filenames and contents."""

    async def scenario():
        api = SimpleNamespace(post=AsyncMock(return_value=json.dumps(SCORING_RESPONSE)))
        command = ProcessGameEventsWithPersistence(api, AsyncFileManager(tmp_path))
        state = await command.execute({"game": 12345})
        assert state.game_id == 12345
        api.post.assert_awaited_once_with({"game": 12345}, use_cache=True)
        assert {path.name: path.read_text() for path in tmp_path.iterdir()} == EXPECTED_OVERLAYS

    asyncio.run(scenario())
