import asyncio
from src.application.services.game_service import GameService
from src.infrastructure.persistence.async_file_manager import AsyncFileManager


class GameClockService:
    """Separate service for game clock management"""

    def __init__(self, game_service: GameService, file_manager: AsyncFileManager):
        self.game_service = game_service
        self.file_manager = file_manager
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self, game_id: int, duration_minutes: int) -> asyncio.Task:
        """Start the clock and return its running task for supervision."""
        if self._running:
            raise RuntimeError("Game clock already running")

        self._running = True
        self._task = asyncio.create_task(
            self.game_service.run_game_clock(game_id, duration_minutes)
        )
        print(f"Game clock started for game {game_id}")
        return self._task

    async def stop(self):
        """Stop the game clock"""
        if not self._running:
            return

        self._running = False
        task, self._task = self._task, None
        if task is not None:
            if not task.done():
                task.cancel()
            # Failures are observed by the supervisor through the returned task.
            await asyncio.gather(task, return_exceptions=True)
        print("Game clock stopped")

    def is_running(self) -> bool:
        """Check if clock is running"""
        return self._running
