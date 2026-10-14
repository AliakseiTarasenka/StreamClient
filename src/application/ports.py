"""Small application interfaces consumed by the command-line presentation."""

from typing import Protocol

from src.domain.models.game_state import GameState


class GameQueries(Protocol):
    """Queries needed to display a schedule or persist a game snapshot."""

    async def get_game_schedule(self, date: str) -> str: ...

    async def get_game_events_with_persistence(self, game_id: int) -> GameState: ...


class LiveSession(Protocol):
    """A live session that returns only after its services have been cleaned up."""

    async def run(self, game_id: int, duration_minutes: int) -> None: ...
