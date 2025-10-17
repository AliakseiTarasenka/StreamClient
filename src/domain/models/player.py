from dataclasses import dataclass


@dataclass
class Player:
    """Player entity"""

    player_id: str
    name: str
    team: str
