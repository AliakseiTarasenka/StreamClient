import argparse
from collections.abc import Callable, Sequence

from config.settings import Settings
from src.application.ports import GameQueries, LiveSession


class CLIHandler:
    """Parse commands and display results; delegate game and lifecycle operations."""

    def __init__(
        self,
        game_service: GameQueries,
        live_session: LiveSession,
        settings: Settings,
        output: Callable[[str], None] = print,
    ):
        self.game_service = game_service
        self.live_session = live_session
        self.settings = settings
        self.output = output

    @staticmethod
    def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
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

        return parser.parse_args(argv)

    async def handle(self, argv: Sequence[str] | None = None):
        """Handle CLI execution"""
        args = self.parse_arguments(argv)

        # Determine game duration based on settings
        duration = self.settings.game_duration
        self.output(f"Using Game duration: {duration} minutes")

        try:
            if args.start and args.game:
                await self._handle_start_mode(args.game, duration)
            elif args.game:
                await self._handle_game_query(args.game)
            elif args.date:
                await self._handle_schedule_query(args.date)
            else:
                self.output("Error: Please specify either --game or --date")
                return
        except KeyboardInterrupt:
            self.output("\nOperation cancelled by user")
        except Exception as e:
            self.output(f"Error: {e}")
            raise

    async def _handle_schedule_query(self, date: str):
        self.output(f"Fetching schedule for {date}:")
        result = await self.game_service.get_game_schedule(date)
        self.output(result)

    async def _handle_game_query(self, game_id: int):
        self.output(f"Fetching game {game_id}:")
        result = await self.game_service.get_game_events_with_persistence(game_id)
        self.output(str(result))

    async def _handle_start_mode(self, game_id: int, duration: int):
        """Delegate the entire live lifecycle to the injected application service."""
        if not self.settings.enable_websocket:
            self.output("WebSocket support not enabled. Set ENABLE_WEBSOCKET=true in .env")
        self.output(f"Starting game {game_id} with {duration}-minute clock...")
        await self.live_session.run(game_id, duration)
        self.output("Shutdown complete.")
