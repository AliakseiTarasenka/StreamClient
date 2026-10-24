import json
from typing import Any, Optional

from src.domain.models.game_event import GameEvent
from src.domain.models.game_state import GameState


class GameEventParser:
    """Parse game event data"""

    @staticmethod
    def parse_event_data(response_text: str) -> GameState:
        """Parse the response text into a GameState object with GameEvent instances."""
        try:
            event_data = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise ValueError("Failed to decode JSON from response text.") from exc

        event_data = GameEventParser._require_object(event_data, "response")
        timing = GameEventParser._require_object(event_data.get("ts", {}), "ts")
        players = GameEventParser._require_object(event_data.get("p", {}), "p")

        game_state = GameState(
            game_id=event_data.get("game_id", 0),
            game_time=timing.get("time"),
            game_stopwatch_timestamp=timing.get("ds"),
            game_stopped=timing.get("stop", True),
            home_score=str(event_data.get("h", 0)),
            away_score=str(event_data.get("a", 0)),
            home_team_name=event_data.get("hn", ""),
            home_team_abbr=event_data.get("ha", ""),
            away_team_name=event_data.get("an", ""),
            away_team_abbr=event_data.get("aa", ""),
        )

        # Parse players
        game_state.home_players = GameEventParser._parse_roster(players.get("h", {}), "p.h")
        game_state.away_players = GameEventParser._parse_roster(players.get("a", {}), "p.a")

        # Parse events
        events_data = event_data.get("e", [])
        if not isinstance(events_data, list):
            raise ValueError("e must be an array of events.")
        game_events: list[GameEvent] = []

        for index, raw_event in enumerate(events_data):
            event = GameEventParser._require_object(raw_event, f"e[{index}]")
            if event.get("y") != "S":
                continue  # Only process scoring events

            if not isinstance(event.get("t"), int) or isinstance(event["t"], bool):
                raise ValueError(f"e[{index}].t must be an integer scoring timestamp.")
            if not isinstance(event.get("e"), str) or not event["e"]:
                raise ValueError(f"e[{index}].e must be a nonempty team marker.")
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
    def _require_object(value: Any, path: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object.")
        return value

    @staticmethod
    def _parse_roster(value: Any, path: str) -> dict[str, str]:
        roster = GameEventParser._require_object(value, path)
        if any(not isinstance(name, str) for name in roster.values()):
            raise ValueError(f"{path} must map player identifiers to names.")
        return roster

    @staticmethod
    def _get_player_name(
        game_state: GameState, team: str, shirt_number: Optional[int]
    ) -> Optional[str]:
        """Get the player's name for a team and shirt number"""
        if shirt_number is None:
            return None

        players = game_state.home_players if team == "h" else game_state.away_players
        return players.get(str(shirt_number))
