"""Small contracts for application operations and their infrastructure adapters."""

from typing import Any, Protocol

from src.domain.models.game_state import GameState


class GameAPI(Protocol):
    """HTTP operation used by schedule and event queries."""

    async def post(self, data: dict[str, Any], use_cache: bool = True) -> str: ...


class OverlayWriter(Protocol):
    """File operations needed to persist an overlay snapshot."""

    async def write_text(self, filename: str, content: str) -> None: ...

    async def write_roster(self, filename: str, players: dict[str, str]) -> None: ...


class GameSnapshots(Protocol):
    """Read a snapshot and persist that same snapshot without another request."""

    async def get_game_events(self, game_id: int) -> GameState: ...

    async def persist_game_state(self, game_state: GameState) -> None: ...


class GameUpdatePublisher(Protocol):
    """Publish a JSON-compatible snapshot, raising when delivery needs retrying."""

    async def broadcast_game_update(self, game_id: int, current_state: dict[str, Any]) -> None: ...


class GameClock(Protocol):
    """Clock loop supervised by the live service adapter."""

    async def run_game_clock(self, game_id: int, duration_minutes: int) -> None: ...


class GameQueries(Protocol):
    """Queries needed to display a schedule or persist a game snapshot."""

    async def get_game_schedule(self, date: str) -> str: ...

    async def get_game_events_with_persistence(self, game_id: int) -> GameState: ...


class LiveSession(Protocol):
    """A live session that returns only after its services have been cleaned up."""

    async def run(self, game_id: int, duration_minutes: int) -> None: ...
