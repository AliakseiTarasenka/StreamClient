"""
High-level game service orchestrating business logic
"""

import asyncio
import math
import time
from src.infrastructure.api.client import APIClientPool
from src.infrastructure.persistence.async_file_manager import AsyncFileManager
from src.domain.models.game_state import GameState


class GameService:
    """High-level service for game operations"""

    def __init__(self, api_client: APIClientPool, file_manager: AsyncFileManager):
        self.api_client = api_client
        self.file_writer = file_manager

    async def get_game_schedule(self, date: str) -> str:
        """Get game schedule for a specific date"""
        from src.application.commands.process_game import ProcessGameSchedule

        command = ProcessGameSchedule(self.api_client)
        data = {"schedule": date, "date": date}
        return await command.execute(data)

    async def get_game_events(self, game_id: int) -> GameState:
        """Get game events for a specific game"""
        from src.application.commands.process_game import ProcessGameEvents

        command = ProcessGameEvents(self.api_client)
        data = {"game": game_id, "update": "true", "players": "true", "teams": "true"}
        return await command.execute(data)

    async def get_game_events_with_persistence(self, game_id: int) -> GameState:
        """Get game events and persist to files"""
        from src.application.commands.process_game import ProcessGameEventsWithPersistence

        command = ProcessGameEventsWithPersistence(self.api_client, self.file_writer)
        data = {"game": game_id, "update": "true", "players": "true", "teams": "true"}
        return await command.execute(data)

    async def run_game_clock(self, game_id: int, duration_minutes: int):
        """Run game clock with countdown and file updates"""
        total_seconds = duration_minutes * 60
        game_time = 0
        game_stopped = True
        game_stopwatch_timestamp = 0
        events_request_sent = False
        last_now = 0

        try:
            while True:
                now = round(time.time())

                if last_now != now:
                    last_now = now

                    # Calculate remaining time
                    if game_stopped:
                        remaining_seconds = total_seconds - game_time
                    else:
                        elapsed_time = game_time + now - game_stopwatch_timestamp
                        remaining_seconds = total_seconds - elapsed_time

                    if remaining_seconds < 0:
                        remaining_seconds = 0

                    # Format time
                    mins, secs = divmod(remaining_seconds, 60)
                    time_str = f"{mins:02}:{secs:02}"

                    # Write clock to file
                    await self.file_writer.write_text("clock.txt", time_str)
                    print(time_str)

                    # Trigger event checking every 5 seconds
                    if not events_request_sent and now % 5 == 0:
                        events_request_sent = True

                        # Update clock state from API
                        game_state = await self.get_game_events(game_id)
                        if game_state.game_time is not None:
                            game_time = math.ceil(int(game_state.game_time) / 10)
                        if game_state.game_stopwatch_timestamp is not None:
                            game_stopwatch_timestamp = round(
                                int(game_state.game_stopwatch_timestamp) / 10
                            )
                        game_stopped = game_state.game_stopped

                    elif events_request_sent and now % 5 != 0:
                        events_request_sent = False

                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            print("Game clock stopped")
            raise
        except Exception as e:
            print(f"Error in game clock: {e}")
            raise
