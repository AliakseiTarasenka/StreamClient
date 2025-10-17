import json
from typing import Optional

from src.domain.models.game_event import GameEvent
from src.domain.models.game_state import GameState


class GameEventParser:
    """Parse game event data"""

    @staticmethod
    def parse_event_data(response_text: str) -> GameState:
        """Parse the response text into a GameState object with GameEvent instances."""
        try:
            event_data = json.loads(response_text)
        except json.JSONDecodeError:
            raise ValueError("Failed to decode JSON from response text.")

        game_state = GameState(
            game_id=event_data.get("game_id", 0),
            game_time=event_data.get("ts", {}).get("time"),
            game_stopwatch_timestamp=event_data.get("ts", {}).get("ds"),
            game_stopped=event_data.get("ts", {}).get("stop", True),
            home_score=str(event_data.get("h", 0)),
            away_score=str(event_data.get("a", 0)),
            home_team_name=event_data.get("hn", ""),
            home_team_abbr=event_data.get("ha", ""),
            away_team_name=event_data.get("an", ""),
            away_team_abbr=event_data.get("aa", ""),
        )

        # Parse players
        players_data = event_data.get("p") or {}
        game_state.home_players = players_data.get("h", {})
        game_state.away_players = players_data.get("a", {})

        # Parse events
        events_data = event_data.get("e", [])
        game_events: list[GameEvent] = []

        for event in events_data:
            if event.get("y") != "S":
                continue  # Only process scoring events

            game_event = GameEvent(
                event_time=event["t"],
                team=event["e"],
                event_type=event["y"],
                assist=GameEventParser._get_player_name(game_state, event["e"], event.get("a")),
                scorer=GameEventParser._get_player_name(game_state, event["e"], event.get("s")),
                home_score=str(event.get("hs", "")),
                away_score=str(event.get("as", "")),
            )
            game_events.append(game_event)

        game_state.events = game_events

        # Extract latest scorer/assist
        if game_state.events:
            latest = max(game_state.events, key=lambda e: e.event_time)
            game_state.latest_scorer = latest.scorer
            game_state.latest_assist = latest.assist
            game_state.home_score = latest.home_score or game_state.home_score
            game_state.away_score = latest.away_score or game_state.away_score

        return game_state

    @staticmethod
    def _get_player_name(
        game_state: GameState, team: str, shirt_number: Optional[int]
    ) -> Optional[str]:
        """Get the player's name for a team and shirt number"""
        if shirt_number is None:
            return None

        players = game_state.home_players if team == "h" else game_state.away_players
        return players.get(str(shirt_number))
