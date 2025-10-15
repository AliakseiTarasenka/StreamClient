from abc import ABC, abstractmethod
from typing import Any, Dict

from src.infrastructure.api.client import APIClientPool
from src.infrastructure.persistence.async_file_manager import AsyncFileManager
from src.application.parsers.game_parser import GameParser
from src.application.parsers.event_parser import GameEventParser
from src.application.parsers.game_data_extractor import GameDataExtractor
from src.domain.models.game_state import GameState


class Command(ABC):
    """Abstract base command"""

    def __init__(self, api_client: APIClientPool):
        self.api_client = api_client

    @abstractmethod
    async def execute(self, data: Dict[str, Any]) -> Any:
        """Execute the command"""
        pass


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

    def __init__(self, api_client: APIClientPool, file_manager: AsyncFileManager):
        super().__init__(api_client)
        self.file_manager = file_manager
        self.extractor = GameDataExtractor()

    async def execute(self, data: Dict[str, Any]) -> str:
        """Execute game events retrieval and persist to files"""
        response = await self.api_client.post(data, use_cache=True)
        game_state = GameEventParser.parse_event_data(response)

        # Persist game state
        await self._persist_game_state(game_state)

        return str(game_state)

    async def _persist_game_state(self, game_state: GameState) -> None:
        """Persist game state to files"""
        # Write team rosters
        await self.file_manager.write_roster("home_roster.txt", game_state.home_players)
        await self.file_manager.write_roster("away_roster.txt", game_state.away_players)

        # Write team names
        await self.file_manager.write_text("home_name.txt", game_state.home_team_abbr)
        await self.file_manager.write_text("away_name.txt", game_state.away_team_abbr)
        await self.file_manager.write_text("home_name_full.txt", game_state.home_team_name)
        await self.file_manager.write_text("away_name_full.txt", game_state.away_team_name)

        # Write scores
        home_score, away_score, scorer, assist = self.extractor.extract_latest_scores(game_state)
        await self.file_manager.write_text("home_score.txt", home_score)
        await self.file_manager.write_text("away_score.txt", away_score)
        await self.file_manager.write_text("scorer.txt", scorer)
        await self.file_manager.write_text("assist.txt", assist)


class CommandFactory:
    """Factory for creating commands"""

    def __init__(self, api_client: APIClientPool, file_manager: AsyncFileManager):
        self.api_client = api_client
        self.file_manager = file_manager

    def create_command(self, command_type: str) -> Command:
        """Create command based on type"""
        commands = {
            "game_schedule": lambda: ProcessGameSchedule(self.api_client),
            "game_events": lambda: ProcessGameEvents(self.api_client),
            "game_events_persist": lambda: ProcessGameEventsWithPersistence(
                self.api_client, self.file_manager
            ),
        }

        if command_type not in commands:
            raise ValueError(f"Invalid command type. Available: {', '.join(commands.keys())}")

        return commands[command_type]()
