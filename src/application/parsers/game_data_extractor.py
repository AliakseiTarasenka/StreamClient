from src.domain.models.game_state import GameState


class GameDataExtractor:
    """Extract specific data from game state"""

    @staticmethod
    def extract_latest_scores(game_state: GameState) -> tuple:
        """Extract latest scores, scorer and assist"""
        return (
            game_state.home_score,
            game_state.away_score,
            game_state.latest_scorer or " ",
            game_state.latest_assist or " ",
        )

    @staticmethod
    def extract_team_info(game_state: GameState) -> dict:
        """Extract team information"""
        return {
            "home_name": game_state.home_team_name,
            "home_abbr": game_state.home_team_abbr,
            "away_name": game_state.away_team_name,
            "away_abbr": game_state.away_team_abbr,
        }
