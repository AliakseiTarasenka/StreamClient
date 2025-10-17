"""
Polls API and streams updates via WebSocket
"""

import asyncio
from typing import Set

from src.infrastructure.api.client import APIClientPool
from src.infrastructure.websocket.server import WebSocketGameServer
from src.application.parsers.event_parser import GameEventParser


class GameEventStreamer:
    """Polls API and pushes updates via WebSocket"""

    def __init__(
        self, api_client: APIClientPool, ws_server: WebSocketGameServer, polling_interval: int = 2
    ):
        self.api_client = api_client
        self.ws_server = ws_server
        self.polling_interval = polling_interval
        self.active_games: Set[int] = set()
        self._tasks: dict = {}
        self._last_states: dict = {}

    async def start_monitoring(self, game_id: int):
        """Start monitoring a game"""
        if game_id in self.active_games:
            print(f"Already monitoring game {game_id}")
            return

        self.active_games.add(game_id)
        task = asyncio.create_task(self._poll_game(game_id))
        self._tasks[game_id] = task
        print(f"Started monitoring game {game_id}")

    async def stop_monitoring(self, game_id: int):
        """Stop monitoring a game"""
        if game_id not in self.active_games:
            return

        self.active_games.discard(game_id)

        # Cancel the polling task
        if game_id in self._tasks:
            task = self._tasks[game_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del self._tasks[game_id]

        # Clear cached state
        if game_id in self._last_states:
            del self._last_states[game_id]

        print(f"Stopped monitoring game {game_id}")

    async def _poll_game(self, game_id: int):
        """Poll game updates and broadcast via WebSocket"""
        data = {"game": game_id, "update": "true", "players": "true", "teams": "true"}

        error_count = 0
        max_errors = 5

        while game_id in self.active_games:
            try:
                # Fetch game data
                response = await self.api_client.post(data, use_cache=False)
                game_state = GameEventParser.parse_event_data(response)
                current_state = game_state.to_dict()

                # Only broadcast if state changed
                last_state = self._last_states.get(game_id)
                if current_state != last_state:
                    await self.ws_server.broadcast_game_update(game_id, current_state)
                    self._last_states[game_id] = current_state
                    print(f"Broadcasted update for the game {game_id}")

                # Reset error count on success
                error_count = 0
                await asyncio.sleep(self.polling_interval)

            except asyncio.CancelledError:
                print(f"Polling cancelled for game {game_id}")
                break
            except Exception as e:
                error_count += 1
                print(f"Error polling game {game_id} (attempt {error_count}/{max_errors}): {e}")

                if error_count >= max_errors:
                    print(f"Max errors reached for game {game_id}, stopping monitor")
                    await self.stop_monitoring(game_id)
                    break

                # Exponential backoff
                await asyncio.sleep(self.polling_interval * (error_count + 1))

    def get_monitored_games(self) -> list:
        """Get list of currently monitored games"""
        return list(self.active_games)

    def is_monitoring(self, game_id: int) -> bool:
        """Check if a game is being monitored"""
        return game_id in self.active_games

    async def stop_all(self):
        """Stop monitoring all games"""
        games = list(self.active_games)
        for game_id in games:
            await self.stop_monitoring(game_id)
