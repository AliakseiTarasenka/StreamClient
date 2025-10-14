from dataclasses import dataclass


@dataclass
class Game:
    """Game entity"""

    game_id: int
    date: str
    time: str
    home_team: str
    home_abbr: str
    home_score: str
    away_team: str
    away_abbr: str
    away_score: str
    is_finished: bool
    division: str

    def __str__(self):
        return (
            f"Game ID: {self.game_id}\n"
            f"Date: {self.date} Start Time: {self.time}\n"
            f"Home Team: {self.home_team} ({self.home_abbr}) - {self.home_score}\n"
            f"Away Team: {self.away_team} ({self.away_abbr}) - {self.away_score}\n"
            f"Division: {self.division}\n"
            f"Game Finished: {'Yes' if self.is_finished else 'No'}\n"
        )
