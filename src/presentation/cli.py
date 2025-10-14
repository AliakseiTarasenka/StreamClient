import argparse
import asyncio
import json
from src.application.services.game_service import GameService
from src.application.services.game_clock_service import GameClockService
from src.application.commands.factory import CommandFactory
from config.settings import Settings


class CLIHandler:
    """Handles CLI argument parsing and execution"""

    def __init__(
        self, game_service: GameService, command_factory: CommandFactory, settings: Settings
    ):
        self.game_service = game_service
        self.command_factory = command_factory
        self.settings = settings

    @staticmethod
    def parse_arguments() -> argparse.Namespace:
        """Parse command-line arguments"""
        parser = argparse.ArgumentParser(
            description="Ultimate Frisbee Game Information API Client",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Get schedule for a date
  python main.py --date 2025-10-05

  # Get game events
  python main.py --game 12345

  # Start game with a clock and websocket connection
  python main.py --game 12345 --start
            """,
        )
        parser.add_argument("--game", type=int, help="Game ID to query")
        parser.add_argument("--date", help="Date for checking the schedule (format: YYYY-MM-DD)")
        parser.add_argument(
            "--start", action="store_true", help="Start timer and process game events"
        )

        return parser.parse_args()

    async def handle(self):
        """Handle CLI execution"""
        args = self.parse_arguments()

        # Determine game duration based on settings
        duration = self.settings.game_duration
        print(f"Using Game duration: {duration} minutes")

        try:
            if args.start and args.game:
                await self._handle_start_mode(args.game, duration)
            elif args.game:
                await self._handle_game_query(args.game)
            elif args.date:
                await self._handle_schedule_query(args.date)
            else:
                print("Error: Please specify either --game or --date")
                return
        except KeyboardInterrupt:
            print("\nOperation cancelled by user")
        except Exception as e:
            print(f"Error: {e}")
            raise

    async def _handle_schedule_query(self, date: str):
        print(f"Fetching schedule for {date} :")
        result = await self.game_service.get_game_schedule(date)
        print(result)

    async def _handle_game_query(self, game_id: int):
        print(f"Fetching game {game_id} :")
        result = await self.game_service.get_game_events_with_persistence(game_id)
        print(result)

    async def _handle_start_mode(self, game_id: int, duration: int):
        """Start WebSocket + game monitoring + clock"""
        if not self.game_service.ws_server or not self.game_service.event_streamer:
            print("WebSocket support not enabled. Set ENABLE_WEBSOCKET=true in .env")
            return

        print(f"Starting game {game_id} with {duration} minute clock...")
        # we are running tasks concurrently: clock, writing to a file and using websocket
        ws_task = asyncio.create_task(self.game_service.ws_server.start())
        monitor_task = asyncio.create_task(self.game_service.start_game_monitoring(game_id))
        clock_service = GameClockService(self.game_service, self.game_service.file_writer)
        clock_task = asyncio.create_task(clock_service.start(game_id, duration))
        try:
            await asyncio.gather(ws_task, monitor_task, clock_task)
        except KeyboardInterrupt:
            print("\nStopping all services...")
        finally:
            await self.game_service.stop_game_monitoring(game_id)
            await self.game_service.ws_server.stop()
            await clock_service.stop()
            print("Shutdown complete.")
