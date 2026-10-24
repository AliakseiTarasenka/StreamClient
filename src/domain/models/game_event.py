from dataclasses import dataclass


@dataclass
class GameEvent:
    """Game event entity (only scoring events, not every game event...)"""

    event_time: int
    team: str
    event_type: str
    assist: str | None = ""
    scorer: str | None = ""
    home_score: str = ""
    away_score: str = ""

    def to_dict(self) -> dict[str, int | str | None]:
        """Expose the stable JSON event contract, preserving unknown players as null."""
        return {
            "event_time": self.event_time,
            "team": self.team,
            "event_type": self.event_type,
            "assist": self.assist,
            "scorer": self.scorer,
            "home_score": self.home_score,
            "away_score": self.away_score,
        }

    def __str__(self):
        details = f"{self.event_time}s {self.team.upper()} {self.event_type}"
        if self.event_type == "S":
            details += (
                f" (Assist: {self.assist}, Scorer: {self.scorer}, "
                f"Scores: {self.home_score}-{self.away_score})"
            )
        return details
