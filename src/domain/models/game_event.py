from dataclasses import dataclass
from typing import Optional


@dataclass
class GameEvent:
    """Game event entity (only scoring events, not every game event...)"""

    event_time: int
    team: str
    event_type: str
    assist: Optional[str] = None
    scorer: Optional[str] = None
    home_score: Optional[str] = None
    away_score: Optional[str] = None

    def __str__(self):
        details = f"{self.event_time}s {self.team.upper()} {self.event_type}"
        if self.event_type == "S":
            details += f" (Assist: {self.assist}, Scorer: {self.scorer}, Scores: {self.home_score}-{self.away_score})"
        return details
