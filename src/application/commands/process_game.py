from abc import ABC, abstractmethod
from typing import Any, Dict

from src.application.commands.persist_game_state import PersistGameState
from src.application.ports import GameAPI, OverlayWriter
from src.application.parsers.game_parser import GameParser
from src.application.parsers.event_parser import GameEventParser
from src.domain.models.game_state import GameState


class Command(ABC):
    """Abstract base command"""

    def __init__(self, api_client: GameAPI):
        self.api_client = api_client

    @abstractmethod
    async def execute(self, data: Dict[str, Any]) -> Any:
        """Execute the command"""


class ProcessGameSchedule(Command):
    """Command to process game schedule"""

    async def execute(self, data: Dict[str, Any]) -> str:
        """Execute game schedule retrieval"""
        response = await self.api_client.post(data)
        games = GameParser.parse(response)
        return "\n".join(str(game) for game in games)


class ProcessGameEvents(Command):
    """Command to process game events without side effects"""

    async def execute(self, data: Dict[str, Any]) -> GameState:
        """Execute game events retrieval and return GameState"""
        response = await self.api_client.post(data, use_cache=True)
        game_state = GameEventParser.parse_event_data(response)
        return game_state


class ProcessGameEventsWithPersistence(Command):
    """Command to process game events with file persistence"""

    def __init__(self, api_client: GameAPI, file_manager: OverlayWriter):
        super().__init__(api_client)
        self.persistence = PersistGameState(file_manager)

    async def execute(self, data: Dict[str, Any]) -> GameState:
        """Execute game events retrieval and persist to files"""
        response = await self.api_client.post(data, use_cache=True)
        game_state = GameEventParser.parse_event_data(response)

        # Persist game state
        await self.persistence.execute(game_state)

        return game_state
