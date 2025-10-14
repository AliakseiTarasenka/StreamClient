import json
from typing import List

from src.domain.models.game import Game


class GameParser:
    """Parse game schedule data"""

    @staticmethod
    def parse(response_text: str) -> List[Game]:
        """Parse the response text into Game objects"""
        if not response_text.strip():
            return []

        try:
            games_data = json.loads(response_text)
        except json.JSONDecodeError:
            raise ValueError("Failed to decode JSON from response text.")

        if not isinstance(games_data, list):
            raise ValueError("JSON content is not formatted as a list of games.")

        games = []
        for game in games_data:
            try:
                parsed_game = Game(
                    game_id=game["i"],
                    date=game["d"],
                    time=game["t"],
                    home_team=game["hn"],
                    home_abbr=game["ha"],
                    home_score=game.get("h", "TBD"),
                    away_team=game["an"],
                    away_abbr=game["aa"],
                    away_score=game.get("a", "TBD"),
                    is_finished=game["e"],
                    division=game["dv"],
                )
                games.append(parsed_game)
            except KeyError as e:
                print(f"Warning: Skipping a game due to missing required attribute: {e}")
            except Exception as e:
                print(f"Warning: An error occurred while processing a game: {e}")

        return games
