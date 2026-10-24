"""Regression tests for broadcasts over the supported websockets connection API."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from src.application.parsers.event_parser import GameEventParser
from src.domain.models.game_state import GameState
from src.infrastructure.websocket.server import WebSocketGameServer


async def subscribe(client, game_id):
    """Wait for the acknowledgment so the server has registered this connection."""
    await client.send(json.dumps({"action": "subscribe", "game_id": game_id}))
    reply = await asyncio.wait_for(client.recv(), timeout=2)
    assert json.loads(reply) == {"status": "subscribed", "game_id": int(game_id)}


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
                    game_server._subscriptions[closed_connection] = 12345
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


def test_parsed_scoring_snapshot_is_json_serializable_and_replayed_to_late_subscriber():
    """The wire event fields preserve scores, mapped names, and unknown-player nulls."""

    async def scenario():
        server = WebSocketGameServer()
        state = GameEventParser.parse_event_data(
            json.dumps(
                {
                    "game_id": 12345,
                    "p": {"h": {"7": "Scorer"}, "a": {}},
                    "e": [{"t": 10, "e": "h", "y": "S", "s": 7, "a": 99, "hs": 1, "as": 0}],
                }
            )
        ).to_dict()
        assert state["events"] == [
            {
                "event_time": 10,
                "team": "h",
                "event_type": "S",
                "assist": None,
                "scorer": "Scorer",
                "home_score": "1",
                "away_score": "0",
            }
        ]
        await server.broadcast_game_update(12345, state)
        # Cached envelopes must not share mutable input with their caller.
        state["home_score"] = "changed later"
        async with serve(server.handle_client, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            async with connect(f"ws://127.0.0.1:{port}") as client:
                await subscribe(client, "12345")
                message = json.loads(await asyncio.wait_for(client.recv(), 2))
                assert message["type"] == "game_update"
                assert message["game_id"] == 12345
                assert message["payload"]["home_score"] == "1"
                assert message["payload"]["events"] == state["events"]
                assert message["payload"]["latest_assist"] is None

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_invalid_requests_keep_connection_usable_and_preserve_subscription():
    """Bad JSON, shapes and IDs return errors; only a valid subscribe changes routing."""

    async def scenario():
        server = WebSocketGameServer()
        invalid_messages = [
            "{",
            b"\xff",
            "[]",
            "null",
            "3",
            "9" * 5000,
            "true",
            '"text"',
            json.dumps({"action": "unknown"}),
        ]
        invalid_messages.extend(
            json.dumps({"action": "subscribe", "game_id": value})
            for value in (
                None,
                True,
                False,
                0,
                -1,
                1.2,
                "",
                "0",
                "-1",
                "1.2",
                " 12",
                "+12",
                [],
                {},
                "9" * 5000,
            )
        )
        invalid_messages.append(json.dumps({"action": "subscribe"}))
        async with serve(server.handle_client, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            async with connect(f"ws://127.0.0.1:{port}") as client:
                await subscribe(client, 12345)
                for request in invalid_messages:
                    await client.send(request)
                    reply = json.loads(await asyncio.wait_for(client.recv(), 2))
                    assert set(reply) == {"error"}
                await server.broadcast_game_update(12345, {"events": []})
                assert json.loads(await asyncio.wait_for(client.recv(), 2))["game_id"] == 12345
                await subscribe(client, "00012346")
                await server.broadcast_game_update(12346, {"events": []})
                assert json.loads(await asyncio.wait_for(client.recv(), 2))["game_id"] == 12346

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_subscriptions_route_games_and_replace_previous_game():
    """An unsubscribed peer receives nothing; each connection selects a single game."""

    async def scenario():
        server = WebSocketGameServer()
        async with serve(server.handle_client, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}"
            async with connect(uri) as first, connect(uri) as second, connect(uri) as idle:
                await subscribe(first, 1)
                await subscribe(second, 2)
                await server.broadcast_game_update(1, {"version": 1})
                assert json.loads(await asyncio.wait_for(first.recv(), 2))["game_id"] == 1
                await server.broadcast_game_update(2, {"version": 2})
                assert json.loads(await asyncio.wait_for(second.recv(), 2))["game_id"] == 2
                await subscribe(first, 2)
                assert json.loads(await asyncio.wait_for(first.recv(), 2))["payload"] == {
                    "version": 2
                }
                await server.broadcast_game_update(1, {"version": 3})
                await server.broadcast_game_update(2, {"version": 4})
                for client in (first, second):
                    assert json.loads(await asyncio.wait_for(client.recv(), 2))["payload"] == {
                        "version": 4
                    }
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(idle.recv(), 0.05)

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_replay_finishes_before_concurrent_new_broadcast():
    """A delayed cached snapshot cannot overwrite the subscriber's newer live state."""

    async def scenario():
        server = WebSocketGameServer()
        await server.broadcast_game_update(1, {"version": 1})
        replay_started = asyncio.Event()
        release_replay = asyncio.Event()
        original_send = server._send

        async def delayed_send(client, message):
            if json.loads(message).get("payload") == {"version": 1}:
                replay_started.set()
                await release_replay.wait()
            await original_send(client, message)

        async with serve(server.handle_client, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            with patch.object(server, "_send", side_effect=delayed_send):
                async with connect(f"ws://127.0.0.1:{port}") as client:
                    await subscribe(client, 1)
                    await replay_started.wait()
                    broadcast = asyncio.create_task(server.broadcast_game_update(1, {"version": 2}))
                    release_replay.set()
                    await broadcast
                    for version in (1, 2):
                        received = json.loads(await asyncio.wait_for(client.recv(), 2))
                        assert received["payload"] == {"version": version}
        assert not server._clients
        assert not server._subscriptions

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_send_timeout_propagates_after_healthy_delivery_and_does_not_leak_tasks():
    """A stuck peer has a finite send deadline while the other send still completes."""

    async def scenario():
        server = WebSocketGameServer(send_timeout=0.05)

        async def blocked_send(_message):
            await asyncio.Event().wait()

        async with serve(server.handle_client, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}"
            async with connect(uri) as stuck:
                await subscribe(stuck, 1)
                connection = next(iter(server._clients))
                async with connect(uri) as healthy:
                    await subscribe(healthy, 1)
                    tasks_before = asyncio.all_tasks()
                    with patch.object(connection, "send", new=blocked_send):
                        with pytest.raises(TimeoutError):
                            await server.broadcast_game_update(1, {"events": []})
                    assert asyncio.all_tasks() <= tasks_before
                    assert json.loads(await asyncio.wait_for(healthy.recv(), 2))["game_id"] == 1

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_server_cancellation_closes_listener_clients_and_allows_reuse():
    """Transport owns no signals and releases actual sockets before task completion."""

    async def scenario():
        tasks_before = asyncio.all_tasks()
        server = WebSocketGameServer("127.0.0.1", 0)
        with patch.object(asyncio.get_running_loop(), "add_signal_handler") as register:
            task = asyncio.create_task(server.start())
            while not server._running:
                await asyncio.sleep(0)
            port = server._server.sockets[0].getsockname()[1]
            async with connect(f"ws://127.0.0.1:{port}") as client:
                await subscribe(client, 1)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                await client.wait_closed()
                assert not server._server.is_serving()
                assert not server._clients
                assert not server._subscriptions
            reused = asyncio.create_task(server.start())
            while not server._running:
                await asyncio.sleep(0)
            assert not reused.done()
            server.request_shutdown()
            await reused
            await server.stop()
            register.assert_not_called()
        assert asyncio.all_tasks() <= tasks_before

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_bind_failure_leaves_no_running_server_or_tasks():
    """Partial startup propagates the bind failure without scheduling orphaned work."""

    async def scenario():
        async with serve(lambda _connection: asyncio.Event().wait(), "127.0.0.1", 0) as listener:
            tasks_before = asyncio.all_tasks()
            port = listener.sockets[0].getsockname()[1]
            server = WebSocketGameServer("127.0.0.1", port)
            with pytest.raises(OSError):
                await server.start()
            assert not server._running
            assert server._server is None
            assert asyncio.all_tasks() <= tasks_before
            await server.stop()

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_cleanup_error_does_not_replace_start_cancellation():
    """The primary cancellation survives a cleanup failure for the session supervisor."""

    async def scenario():
        server = WebSocketGameServer("127.0.0.1", 0)
        task = asyncio.create_task(server.start())
        try:
            while not server._running:
                await asyncio.sleep(0)
            with patch.object(server, "stop", side_effect=RuntimeError("cleanup failed")):
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
        finally:
            await server.stop()
            await asyncio.gather(task, return_exceptions=True)
        assert not server._server.is_serving()

    asyncio.run(asyncio.wait_for(scenario(), 10))
