import asyncio
from src.infrastructure.api.client import APIClientPool
from src.infrastructure.api.config import APIConfig
from src.infrastructure.persistence.async_file_manager import AsyncFileManager
from src.infrastructure.websocket.server import WebSocketGameServer
from src.application.services.game_service import GameService
from src.application.services.game_clock_service import GameClockService
from src.application.services.live_session import LiveGameSession, ServiceLifecycle
from src.infrastructure.websocket.streamer import GameEventStreamer
from src.infrastructure.signals import ShutdownSignals
from src.presentation.cli import CLIHandler
from config.settings import Settings


def create_live_session(
    game_service: GameService,
    file_manager: AsyncFileManager,
    poll_interval: int,
    ws_server: WebSocketGameServer | None,
) -> LiveGameSession:
    """Wire concrete services to the application lifecycle without starting them."""
    clock = GameClockService(game_service, file_manager)
    streamer = GameEventStreamer(game_service, poll_interval, ws_server)
    services = [
        ServiceLifecycle("clock", clock.start, lambda _game_id: clock.stop()),
    ]
    if ws_server is not None:
        # Bind a non-optional server reference for the lifetime of this session.
        server = ws_server

        async def start_websocket(_game_id: int, _duration: int) -> asyncio.Task[None]:
            return asyncio.create_task(server.start())

        services.append(
            ServiceLifecycle("websocket", start_websocket, lambda _game_id: server.stop())
        )
    services.append(
        ServiceLifecycle(
            "monitor",
            lambda game_id, _duration: streamer.start_monitoring(game_id),
            streamer.stop_monitoring,
        )
    )
    return LiveGameSession(services)


async def main() -> None:
    """Own process signals and translate requested shutdown into normal completion."""
    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("Application must run in an asyncio task")
    with ShutdownSignals(asyncio.get_running_loop(), task.cancel) as signals:
        try:
            await run_application()
        except asyncio.CancelledError:
            if not signals.requested:
                raise


async def run_application() -> None:
    """Compose dependencies, execute the CLI, and release infrastructure resources."""
    settings = Settings()
    config = APIConfig()
    api_client = APIClientPool(
        base_url=config.api_default_url,
        timeout=settings.request_timeout,
        max_connections=settings.max_connections,
        cache_ttl=settings.cache_ttl,
    )
    primary_error: BaseException | None = None
    try:
        file_manager = AsyncFileManager(base_path=settings.output_path)
        game_service = GameService(api_client=api_client, file_manager=file_manager)
        ws_server = None
        if settings.enable_websocket:
            ws_server = WebSocketGameServer(
                host=settings.websocket_host, port=settings.websocket_port
            )
        live_session = create_live_session(
            game_service, file_manager, settings.poll_interval, ws_server
        )
        cli_handler = CLIHandler(game_service, live_session, settings)
        await cli_handler.handle()
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            await api_client.close()
        except BaseException as error:
            if primary_error is None:
                raise
            print(f"Error closing HTTP client: {error}")


if __name__ == "__main__":
    asyncio.run(main())
