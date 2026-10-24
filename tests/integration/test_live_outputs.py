"""The composed live pipeline maintains files and real WebSocket output together."""

import asyncio
from copy import deepcopy
import json
from unittest.mock import patch

import httpx
from websockets.asyncio.client import connect

from main import create_live_session
from src.application.services.game_service import GameService
from src.infrastructure.api.client import APIClientPool
from src.infrastructure.persistence.async_file_manager import AsyncFileManager
from src.infrastructure.websocket.server import WebSocketGameServer
from tests.integration.test_integration import EXPECTED_OVERLAYS, SCORING_RESPONSE


def test_live_scoring_updates_overlays_clock_and_late_subscriber_then_closes(tmp_path):
    async def scenario():
        baseline = asyncio.all_tasks()
        response = deepcopy(SCORING_RESPONSE)
        first_snapshot = asyncio.Event()
        websocket = WebSocketGameServer("127.0.0.1", 0)
        broadcast = websocket.broadcast_game_update

        async def publish(game_id, state):
            await broadcast(game_id, state)
            first_snapshot.set()

        async with APIClientPool(
            "https://scores.example/watch",
            cache_ttl=0,
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response)),
        ) as api:
            files = AsyncFileManager(tmp_path)
            service = GameService(api, files)
            session = create_live_session(service, files, 0, websocket)
            with (
                patch.object(websocket, "broadcast_game_update", side_effect=publish),
                # Keep the real clock between API refresh boundaries; timing itself
                # is covered with controlled time in the clock unit tests.
                patch("src.application.services.game_service.time.time", return_value=101),
            ):
                task = asyncio.create_task(session.run(12345, 25))
                try:
                    await first_snapshot.wait()
                    while not websocket._running:
                        await asyncio.sleep(0)
                    port = websocket._server.sockets[0].getsockname()[1]
                    async with connect(f"ws://127.0.0.1:{port}") as client:
                        await client.send('{"action":"subscribe","game_id":"12345"}')
                        assert json.loads(await client.recv()) == {
                            "status": "subscribed",
                            "game_id": 12345,
                        }
                        first = json.loads(await client.recv())
                        assert first["payload"]["home_score"] == "1"
                        assert first["payload"]["events"][0]["scorer"] == "Alex"
                        response["h"] = response["e"][0]["hs"] = 2
                        response["e"][0]["t"] = 130
                        second = json.loads(await client.recv())
                        assert second["payload"]["home_score"] == "2"
                        expected = {**EXPECTED_OVERLAYS, "home_score.txt": "2"}
                        assert {
                            name: (tmp_path / name).read_text() for name in expected
                        } == expected
                        assert (tmp_path / "clock.txt").read_text() == "25:00"
                        assert not task.done()
                        websocket.request_shutdown()
                        await task
                    assert not websocket._server.is_serving()
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        assert asyncio.all_tasks() <= baseline

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))
