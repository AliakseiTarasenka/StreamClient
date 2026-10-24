"""Poll snapshots, persist overlays, and optionally publish game updates."""

import asyncio

from src.application.ports import GameSnapshots, GameUpdatePublisher
from src.domain.models.game_state import GameState


class GameEventStreamer:
    """Supervised polling with independent persistence and delivery checkpoints."""

    MAX_ERRORS = 5

    def __init__(
        self,
        game_service: GameSnapshots,
        polling_interval: float = 2,
        ws_server: GameUpdatePublisher | None = None,
    ):
        self.game_service = game_service
        self.polling_interval = polling_interval
        self.ws_server = ws_server
        self.active_games: set[int] = set()
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._persisted_states: dict[int, GameState] = {}
        self._delivered_states: dict[int, GameState] = {}

    async def start_monitoring(self, game_id: int) -> asyncio.Task[None]:
        """Start monitoring and return the actual polling task for supervision."""
        if game_id in self.active_games:
            print(f"Already monitoring game {game_id}")
            return self._tasks[game_id]

        self.active_games.add(game_id)
        task = asyncio.create_task(self._poll_game(game_id))
        self._tasks[game_id] = task
        print(f"Started monitoring game {game_id}")
        return task

    async def stop_monitoring(self, game_id: int) -> None:
        """Cancel and await the polling task, then clear its checkpoints."""
        task = self._tasks.pop(game_id, None)
        self.active_games.discard(game_id)
        if task is not None:
            if not task.done():
                task.cancel()
            # The live supervisor owns reporting the task's terminal failure.
            await asyncio.gather(task, return_exceptions=True)
        self._persisted_states.pop(game_id, None)
        self._delivered_states.pop(game_id, None)
        print(f"Stopped monitoring game {game_id}")

    async def _poll_game(self, game_id: int) -> None:
        """Retry each failed stage without treating another stage as its success."""
        errors = {"fetch": 0, "persistence": 0, "delivery": 0}
        try:
            while game_id in self.active_games:
                try:
                    current_state = await self.game_service.get_game_events(game_id)
                except Exception as error:
                    errors["fetch"] += 1
                    await self._retry(game_id, "fetch", errors["fetch"], error)
                    continue
                # An unchanged response is still a successful fetch.
                errors["fetch"] = 0

                try:
                    # Keep file-only mode's historical rewrite-on-every-poll behavior.
                    if self.ws_server is None or current_state != self._persisted_states.get(
                        game_id
                    ):
                        await self.game_service.persist_game_state(current_state)
                        self._persisted_states[game_id] = current_state
                except Exception as error:
                    # A partial write may have replaced the previous good snapshot.
                    self._persisted_states.pop(game_id, None)
                    errors["persistence"] += 1
                    await self._retry(game_id, "persistence", errors["persistence"], error)
                    continue
                errors["persistence"] = 0

                try:
                    if self.ws_server is not None and current_state != self._delivered_states.get(
                        game_id
                    ):
                        await self.ws_server.broadcast_game_update(game_id, current_state.to_dict())
                        self._delivered_states[game_id] = current_state
                except Exception as error:
                    # Some clients or the server cache may have received this state.
                    self._delivered_states.pop(game_id, None)
                    errors["delivery"] += 1
                    await self._retry(game_id, "delivery", errors["delivery"], error)
                    continue
                errors["delivery"] = 0
                await asyncio.sleep(self.polling_interval)
        finally:
            # Cancellation and exhausted retries both reach the supervising task.
            self.active_games.discard(game_id)

    async def _retry(self, game_id: int, operation: str, count: int, error: Exception) -> None:
        """Back off after a failed stage or propagate its original terminal error."""
        print(f"Error during {operation} for game {game_id} ({count}/{self.MAX_ERRORS}): {error}")
        if count >= self.MAX_ERRORS:
            raise error
        await asyncio.sleep(self.polling_interval * (count + 1))

    def get_monitored_games(self) -> list[int]:
        """Get the currently monitored games."""
        return list(self.active_games)

    def is_monitoring(self, game_id: int) -> bool:
        """Check whether a game's polling loop is active."""
        return game_id in self.active_games

    async def stop_all(self) -> None:
        """Stop every registered polling task, including already failed tasks."""
        for game_id in list(self._tasks):
            await self.stop_monitoring(game_id)
