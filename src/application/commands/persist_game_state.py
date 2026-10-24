"""Persist an already parsed snapshot using the established overlay filenames."""

from src.application.parsers.game_data_extractor import GameDataExtractor
from src.application.ports import OverlayWriter
from src.domain.models.game_state import GameState


class PersistGameState:
    """Map domain state to overlays independently of retrieval and transport."""

    def __init__(self, writer: OverlayWriter):
        self.writer = writer

    async def execute(self, game_state: GameState) -> None:
        """Write the ten snapshot files; propagate failures so polling can retry."""
        await self.writer.write_roster("home_roster.txt", game_state.home_players)
        await self.writer.write_roster("away_roster.txt", game_state.away_players)
        await self.writer.write_text("home_name.txt", game_state.home_team_abbr)
        await self.writer.write_text("away_name.txt", game_state.away_team_abbr)
        await self.writer.write_text("home_name_full.txt", game_state.home_team_name)
        await self.writer.write_text("away_name_full.txt", game_state.away_team_name)
        home_score, away_score, scorer, assist = GameDataExtractor.extract_latest_scores(game_state)
        await self.writer.write_text("home_score.txt", home_score)
        await self.writer.write_text("away_score.txt", away_score)
        await self.writer.write_text("scorer.txt", scorer)
        await self.writer.write_text("assist.txt", assist)
