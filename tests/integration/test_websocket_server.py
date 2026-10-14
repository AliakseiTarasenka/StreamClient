"""Regression tests for broadcasts over the supported websockets connection API."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from src.domain.models.game_state import GameState
from src.infrastructure.websocket.server import WebSocketGameServer


async def subscribe(client, game_id):
    """Wait for the acknowledgment so the server has registered this connection."""
    await client.send(json.dumps({"action": "subscribe", "game_id": game_id}))
    reply = await asyncio.wait_for(client.recv(), timeout=2)
    assert json.loads(reply) == {"status": "subscribed", "game_id": game_id}


def test_broadcast_delivers_update_to_all_connected_clients():
    """Both clients receive the complete JSON envelope using real connections."""

    async def scenario():
        game_server = WebSocketGameServer()
        state = GameState(12345, home_score="2", away_score="1").to_dict()
        async with serve(game_server.handle_client, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}"
            async with connect(uri) as first, connect(uri) as second:
                await subscribe(first, 12345)
                await subscribe(second, 12345)
                await game_server.broadcast_game_update(12345, state)
                for client in (first, second):
                    message = await asyncio.wait_for(client.recv(), timeout=2)
                    assert json.loads(message) == {
                        "type": "game_update",
                        "game_id": 12345,
                        "payload": state,
                    }
        assert not game_server._clients

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


def test_closed_connection_does_not_prevent_broadcast_to_other_clients():
    """A stale connection is removed after send fails; healthy clients still receive."""

    async def scenario():
        game_server = WebSocketGameServer()
        disconnected = asyncio.Event()

        async def handle_client(connection):
            try:
                await game_server.handle_client(connection)
            finally:
                disconnected.set()

        async with serve(handle_client, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}"
            async with connect(uri) as closing:
                await subscribe(closing, 12345)
                closed_connection = next(iter(game_server._clients))
                async with connect(uri) as healthy:
                    await subscribe(healthy, 12345)
                    await closing.close()
                    await asyncio.wait_for(disconnected.wait(), timeout=2)
                    # Keep a stale connection to exercise send-time disconnect handling.
                    game_server._clients.add(closed_connection)
                    state = {"home_score": "3", "away_score": "1", "events": []}
                    await game_server.broadcast_game_update(12345, state)
                    message = await asyncio.wait_for(healthy.recv(), timeout=2)
                    assert json.loads(message)["payload"] == state
                    assert closed_connection not in game_server._clients
                    assert len(game_server._clients) == 1
        assert not game_server._clients

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


def test_unexpected_send_failure_is_reported_after_other_clients_receive():
    """Programming errors are not silently discarded by the concurrent sends."""

    async def scenario():
        game_server = WebSocketGameServer()
        async with serve(game_server.handle_client, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}"
            async with connect(uri) as failing:
                await subscribe(failing, 12345)
                failing_connection = next(iter(game_server._clients))
                async with connect(uri) as healthy:
                    await subscribe(healthy, 12345)
                    state = {"events": []}
                    with patch.object(
                        failing_connection,
                        "send",
                        new=AsyncMock(side_effect=RuntimeError("send failed")),
                    ):
                        with pytest.raises(RuntimeError, match="send failed"):
                            await game_server.broadcast_game_update(12345, state)
                    message = await asyncio.wait_for(healthy.recv(), timeout=2)
                    assert json.loads(message)["payload"] == state
        assert not game_server._clients

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))
