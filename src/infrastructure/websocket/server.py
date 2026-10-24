import asyncio
import json

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed


class WebSocketGameServer:
    """Transport for game subscriptions, ordered snapshots, and live updates."""

    def __init__(self, host: str = "localhost", port: int = 8765, *, send_timeout: float = 5):
        self.host = host
        self.port = port
        self._send_timeout = send_timeout
        self._running = False
        self._server: Server | None = None
        self._clients: set[ServerConnection] = set()
        self._subscriptions: dict[ServerConnection, int] = {}
        self._snapshots: dict[int, str] = {}
        # Subscriptions and broadcasts share an ordering boundary: replay cannot
        # deliver an old snapshot after a more recent live update.
        self._delivery_lock = asyncio.Lock()
        self._stop_lock = asyncio.Lock()
        self._shutdown_event = asyncio.Event()

    def _remove_client(self, websocket: ServerConnection) -> None:
        self._clients.discard(websocket)
        self._subscriptions.pop(websocket, None)

    async def handle_client(self, websocket: ServerConnection) -> None:
        """Handle requests until the peer disconnects or the listener closes."""
        self._clients.add(websocket)
        client_addr = websocket.remote_address
        print(f"[WS] Client connected: {client_addr}")
        try:
            async for message in websocket:
                await self.handle_message(websocket, message)
        except ConnectionClosed:
            print(f"[WS] Client disconnected: {client_addr}")
        finally:
            self._remove_client(websocket)

    @staticmethod
    def _parse_game_id(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            try:
                game_id = int(value)
            except ValueError:
                # Also rejects strings exceeding Python's integer digit limit.
                return None
            return game_id if game_id > 0 else None
        return None

    async def _send(self, websocket: ServerConnection, message: str) -> None:
        async with asyncio.timeout(self._send_timeout):
            await websocket.send(message)

    async def handle_message(self, websocket: ServerConnection, message: str | bytes) -> None:
        """Validate a subscription, acknowledge it, then replay its latest snapshot."""
        try:
            data = json.loads(message)
        except ValueError:
            # Includes malformed JSON, invalid UTF-8, and oversized JSON integers.
            await self._send(websocket, json.dumps({"error": "Invalid JSON"}))
            return

        if not isinstance(data, dict):
            await self._send(websocket, json.dumps({"error": "Request must be a JSON object"}))
            return
        if data.get("action") != "subscribe":
            await self._send(websocket, json.dumps({"error": "Unknown action"}))
            return
        game_id = self._parse_game_id(data.get("game_id"))
        if game_id is None:
            await self._send(websocket, json.dumps({"error": "Invalid game_id"}))
            return

        async with self._delivery_lock:
            await self._send(websocket, json.dumps({"status": "subscribed", "game_id": game_id}))
            self._subscriptions[websocket] = game_id
            snapshot = self._snapshots.get(game_id)
            if snapshot is not None:
                await self._send(websocket, snapshot)
        print(f"[WS] Client subscribed to game {game_id}")

    async def broadcast_game_update(self, game_id: int, current_state: dict) -> None:
        """Cache an immutable envelope and attempt delivery to every matching subscriber.

        Closed peers are removed. Other failures propagate after every selected
        send completes; the polling service owns retries and may duplicate updates.
        """
        message = json.dumps({"type": "game_update", "game_id": game_id, "payload": current_state})
        async with self._delivery_lock:
            self._snapshots[game_id] = message
            clients = tuple(
                client for client in self._clients if self._subscriptions.get(client) == game_id
            )
            results = await asyncio.gather(
                *(self._send(client, message) for client in clients), return_exceptions=True
            )
            failure: BaseException | None = None
            sent_count = 0
            for client, result in zip(clients, results):
                if isinstance(result, ConnectionClosed):
                    self._remove_client(client)
                elif isinstance(result, BaseException):
                    failure = failure or result
                else:
                    sent_count += 1
            if failure is not None:
                raise failure
        print(f"[WS] Broadcasted game {game_id} update to {sent_count} clients")

    def request_shutdown(self) -> None:
        """Request normal completion; process signal ownership belongs to the caller."""
        self._shutdown_event.set()

    async def start(self) -> None:
        """Run the listener until shutdown or cancellation, releasing it on every exit."""
        self._shutdown_event.clear()
        primary_error: BaseException | None = None
        try:
            self._server = await serve(self.handle_client, self.host, self.port)
            self._running = True
            print(f"[WS] Server started on ws://{self.host}:{self.port}")
            await self._shutdown_event.wait()
        except BaseException as error:
            primary_error = error
            raise
        finally:
            try:
                await self.stop()
            except Exception as error:
                if primary_error is None:
                    raise
                print(f"[WS] Error during shutdown: {error}")

    async def stop(self) -> None:
        """Close the listener and all peers; safe after partial startup or prior cleanup."""
        async with self._stop_lock:
            self._shutdown_event.set()
            self._running = False
            if self._server is not None:
                self._server.close()
                await self._server.wait_closed()
            self._clients.clear()
            self._subscriptions.clear()
            self._snapshots.clear()
