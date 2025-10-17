import asyncio
from src.infrastructure.api.client import APIClientPool
from src.infrastructure.api.config import APIConfig
from src.infrastructure.persistence.async_file_manager import AsyncFileManager
from src.infrastructure.websocket.server import WebSocketGameServer
from src.infrastructure.websocket.streamer import GameEventStreamer
from src.application.services.game_service import GameService
from src.presentation.cli import CLIHandler
from config.settings import Settings


async def main():
    """Main entry point with dependency injection"""
    # Load configuration
    settings = Settings()
    config = APIConfig()
    # Initialize infrastructure
    api_client = APIClientPool(
        base_url=config.api_default_url,
        max_connections=settings.max_connections,
        cache_ttl=settings.cache_ttl,
    )

    file_manager = AsyncFileManager(base_path=settings.output_path)

    # Initialize WebSocket server if enabled
    ws_server = None
    event_streamer = None

    if settings.enable_websocket:
        ws_server = WebSocketGameServer(host=settings.websocket_host, port=settings.websocket_port)
        event_streamer = GameEventStreamer(
            api_client=api_client, ws_server=ws_server, polling_interval=settings.poll_interval
        )

    # Initialize application services
    game_service = GameService(
        api_client=api_client,
        file_manager=file_manager,
        ws_server=ws_server,
        event_streamer=event_streamer,
    )

    # Handle CLI
    cli_handler = CLIHandler(game_service=game_service, settings=settings)

    try:
        await cli_handler.handle()
    finally:
        await api_client.close()
        if ws_server:
            await ws_server.stop()


if __name__ == "__main__":
    asyncio.run(main())
