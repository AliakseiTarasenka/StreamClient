from dataclasses import dataclass
from typing import Optional


@dataclass
class GameState:
    """Complete game state snapshot"""

    game_id: int
    game_time: Optional[int] = None
    game_stopwatch_timestamp: Optional[int] = None
    game_stopped: bool = True
    home_score: str = "0"
    away_score: str = "0"
    home_team_name: str = ""
    home_team_abbr: str = ""
    away_team_name: str = ""
    away_team_abbr: str = ""
    home_players: dict = None
    away_players: dict = None
    events: list = None
    latest_scorer: str = ""
    latest_assist: str = ""

    def __post_init__(self):
        if self.home_players is None:
            self.home_players = {}
        if self.away_players is None:
            self.away_players = {}
        if self.events is None:
            self.events = []

    def to_dict(self):
        """Convert to dictionary for serialization"""
        return {
            "game_id": self.game_id,
            "game_time": self.game_time,
            "game_stopwatch_timestamp": self.game_stopwatch_timestamp,
            "game_stopped": self.game_stopped,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "teams": {
                "home_name": self.home_team_name,
                "home_abbr": self.home_team_abbr,
                "away_name": self.away_team_name,
                "away_abbr": self.away_team_abbr,
            },
            "players": {
                "home": self.home_players,
                "away": self.away_players,
            },
            "events": self.events,
            "latest_scorer": self.latest_scorer,
            "latest_assist": self.latest_assist,
        }
