"""
Polls API and streams updates via WebSocket
"""

import asyncio
from typing import Set

from src.application.services.game_service import GameService
from src.infrastructure.websocket.server import WebSocketGameServer


class GameEventStreamer:
    """Polls API and pushes updates via WebSocket"""

    def __init__(
        self,
        game_service: GameService,
        polling_interval: int = 2,
        ws_server: WebSocketGameServer = None,
    ):
        self.game_service = game_service
        self.polling_interval = polling_interval
        self.ws_server = ws_server
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
        error_count = 0
        max_errors = 5

        while game_id in self.active_games:
            try:
                # Fetch current game state
                current_state = await self._fetch_game_state(game_id)
                last_state = self._last_states.get(game_id)

                if current_state != last_state:
                    await self._handle_state_change(game_id, current_state)
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

    async def _fetch_game_state(self, game_id: int):
        """
        Fetch the latest game state.
        Use lightweight fetch if WebSocket is active, otherwise persist to file.
        """
        if self.ws_server:
            return await self.game_service.get_game_events(game_id)
        return await self.game_service.get_game_events_with_persistence(game_id)

    async def _handle_state_change(self, game_id: int, current_state):
        """Handle and persist/broadcast game state changes."""
        try:
            # Persist first
            if hasattr(self.game_service, "persist_game_state"):
                await self.game_service.persist_game_state(game_id, current_state)
                print(f"[SAVE] Game {game_id} state persisted.")

            # Then broadcast if WebSocket enabled
            if self.ws_server:
                await self.ws_server.broadcast_game_update(game_id, current_state.to_dict())
                print(f"[WS] Broadcasted update for game {game_id}")
            else:
                print(f"[INFO] WebSocket not enabled for game {game_id}")

        except Exception as e:
            print(f"[WARN] Failed to handle game {game_id}: {e}")

        self._last_states[game_id] = current_state

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
