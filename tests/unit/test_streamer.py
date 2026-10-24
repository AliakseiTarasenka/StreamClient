"""Behavioral polling regressions with no remote API or real overlay output."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.models.game_state import GameState
from src.infrastructure.websocket.streamer import GameEventStreamer


def test_failed_delivery_retries_unchanged_state_without_repeating_persistence():
    """A delivery failure must not advance the delivered snapshot checkpoint."""

    async def scenario():
        initial_tasks = asyncio.all_tasks()
        retried = asyncio.Event()
        snapshot = GameState(12345, home_score="1")
        calls = 0

        async def fetch(_game_id):
            nonlocal calls
            calls += 1
            if calls > 2:
                retried.set()
                await asyncio.Event().wait()
            return snapshot

        service = SimpleNamespace(get_game_events=fetch, persist_game_state=AsyncMock())
        publisher = SimpleNamespace(
            broadcast_game_update=AsyncMock(side_effect=[RuntimeError("send failed"), None])
        )
        streamer = GameEventStreamer(service, 0, publisher)
        task = await streamer.start_monitoring(12345)
        try:
            await retried.wait()
            assert not task.done()
            service.persist_game_state.assert_awaited_once_with(snapshot)
            assert publisher.broadcast_game_update.await_count == 2
        finally:
            await streamer.stop_all()
        assert task.cancelled()
        assert not streamer.active_games
        assert not streamer._tasks
        assert not streamer._persisted_states
        assert not streamer._delivered_states
        assert asyncio.all_tasks() <= initial_tasks

    asyncio.run(asyncio.wait_for(scenario(), 5))


@pytest.mark.parametrize("failure_stage", ["persistence", "delivery"])
def test_output_failure_exhaustion_propagates_original_error(failure_stage):
    """Healthy fetches must not reset failed output attempts indefinitely."""

    async def scenario():
        snapshot = GameState(12345)
        error = RuntimeError(f"{failure_stage} unavailable")
        persist = AsyncMock(side_effect=error if failure_stage == "persistence" else None)
        publish = AsyncMock(side_effect=error if failure_stage == "delivery" else None)
        service = SimpleNamespace(
            get_game_events=AsyncMock(return_value=snapshot), persist_game_state=persist
        )
        streamer = GameEventStreamer(service, 0, SimpleNamespace(broadcast_game_update=publish))
        task = await streamer.start_monitoring(12345)
        try:
            with pytest.raises(RuntimeError) as caught:
                await task
            assert caught.value is error
            assert service.get_game_events.await_count == 5
            assert persist.await_count == (5 if failure_stage == "persistence" else 1)
            assert publish.await_count == (5 if failure_stage == "delivery" else 0)
            assert not streamer.is_monitoring(12345)
        finally:
            await streamer.stop_all()

    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_successful_unchanged_fetch_resets_fetch_error_budget():
    """Only consecutive failed fetches exhaust the budget, even without state changes."""

    async def scenario():
        completed = asyncio.Event()
        snapshot = GameState(12345)
        attempts = iter([snapshot] + [RuntimeError("offline")] * 4 + [snapshot] * 2)
        second_group = iter([RuntimeError("offline again")] * 4 + [snapshot])
        fetches = 0

        async def fetch(_game_id):
            nonlocal fetches
            fetches += 1
            try:
                result = next(attempts) if fetches <= 7 else next(second_group)
            except StopIteration:
                completed.set()
                await asyncio.Event().wait()
                return snapshot
            if isinstance(result, Exception):
                raise result
            return result

        persist = AsyncMock()
        publisher = SimpleNamespace(broadcast_game_update=AsyncMock())
        streamer = GameEventStreamer(
            SimpleNamespace(get_game_events=fetch, persist_game_state=persist), 0, publisher
        )
        task = await streamer.start_monitoring(12345)
        try:
            await completed.wait()
            assert not task.done()
            persist.assert_awaited_once_with(snapshot)
            publisher.broadcast_game_update.assert_awaited_once_with(12345, snapshot.to_dict())
        finally:
            await streamer.stop_all()

    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_failed_persistence_retries_before_publishing():
    """A partially written overlay snapshot is retried and never counted as saved."""

    async def scenario():
        completed = asyncio.Event()
        snapshot = GameState(12345)
        fetches = 0

        async def fetch(_game_id):
            nonlocal fetches
            fetches += 1
            if fetches > 3:
                completed.set()
                await asyncio.Event().wait()
            return snapshot

        persist = AsyncMock(side_effect=[OSError("disk error"), None])
        publisher = SimpleNamespace(broadcast_game_update=AsyncMock())
        streamer = GameEventStreamer(
            SimpleNamespace(get_game_events=fetch, persist_game_state=persist), 0, publisher
        )
        await streamer.start_monitoring(12345)
        try:
            await completed.wait()
            assert persist.await_count == 2
            publisher.broadcast_game_update.assert_awaited_once()
        finally:
            await streamer.stop_all()

    asyncio.run(asyncio.wait_for(scenario(), 5))


@pytest.mark.parametrize("failure_stage", ["persistence", "delivery"])
def test_reverted_snapshot_repairs_partial_failed_output(failure_stage):
    """A partial B failure invalidates A's checkpoint when upstream reverts to A."""

    async def scenario():
        completed = asyncio.Event()
        original = GameState(12345, home_score="0")
        changed = GameState(12345, home_score="1")
        snapshots = iter([original, changed, original])
        written_scores = []
        received_scores = []

        async def fetch(_game_id):
            try:
                return next(snapshots)
            except StopIteration:
                completed.set()
                await asyncio.Event().wait()
                return original

        async def persist(snapshot):
            # Model a partially overwritten overlay before an I/O failure.
            written_scores.append(snapshot.home_score)
            if failure_stage == "persistence" and snapshot is changed:
                raise OSError("partial write")

        async def publish(_game_id, snapshot):
            # Model a client receiving B before another client's send fails.
            received_scores.append(snapshot["home_score"])
            if failure_stage == "delivery" and snapshot["home_score"] == "1":
                raise RuntimeError("partial broadcast")

        streamer = GameEventStreamer(
            SimpleNamespace(get_game_events=fetch, persist_game_state=persist),
            0,
            SimpleNamespace(broadcast_game_update=publish),
        )
        task = await streamer.start_monitoring(12345)
        try:
            await completed.wait()
            assert not task.done()
            assert written_scores == ["0", "1", "0"]
            assert received_scores == (["0"] if failure_stage == "persistence" else ["0", "1", "0"])
        finally:
            await streamer.stop_all()

    asyncio.run(asyncio.wait_for(scenario(), 5))


@pytest.mark.parametrize("websocket_enabled", [False, True])
def test_unchanged_snapshot_persistence_keeps_file_only_compatibility(websocket_enabled):
    """File-only rewrites each poll; streaming writes only pending snapshot changes."""

    async def scenario():
        completed = asyncio.Event()
        snapshot = GameState(12345)
        fetches = 0

        async def fetch(_game_id):
            nonlocal fetches
            fetches += 1
            if fetches > 2:
                completed.set()
                await asyncio.Event().wait()
            return snapshot

        persist = AsyncMock()
        publisher = (
            SimpleNamespace(broadcast_game_update=AsyncMock()) if websocket_enabled else None
        )
        streamer = GameEventStreamer(
            SimpleNamespace(get_game_events=fetch, persist_game_state=persist), 0, publisher
        )
        await streamer.start_monitoring(12345)
        try:
            await completed.wait()
            assert persist.await_count == (1 if websocket_enabled else 2)
        finally:
            await streamer.stop_all()

    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_cancelling_backoff_cleans_up_without_waiting_for_retry_delay():
    """Retry backoff yields to cancellation and leaves no polling task behind."""

    async def scenario():
        initial_tasks = asyncio.all_tasks()
        failed = asyncio.Event()

        async def fetch(_game_id):
            failed.set()
            raise RuntimeError("offline")

        streamer = GameEventStreamer(
            SimpleNamespace(get_game_events=fetch, persist_game_state=AsyncMock()), 60
        )
        task = await streamer.start_monitoring(12345)
        await failed.wait()
        assert await streamer.start_monitoring(12345) is task
        await streamer.stop_all()
        assert task.cancelled()
        assert not streamer.get_monitored_games()
        assert not streamer._tasks
        assert asyncio.all_tasks() <= initial_tasks

    asyncio.run(asyncio.wait_for(scenario(), 5))
