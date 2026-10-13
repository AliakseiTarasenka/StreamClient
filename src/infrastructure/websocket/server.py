import asyncio
import json
import signal
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed


class WebSocketGameServer:
    """Async WebSocket server for broadcasting game updates."""

    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self._running = False
        self._server = None
        self._clients: set[ServerConnection] = set()
        self._shutdown_event = asyncio.Event()

    async def handle_client(self, websocket: ServerConnection):
        """Handle new WebSocket client connections."""
        self._clients.add(websocket)
        client_addr = websocket.remote_address
        print(f"[WS] Client connected: {client_addr}")
        try:
            async for message in websocket:
                await self.handle_message(websocket, message)
        except ConnectionClosed:
            print(f"[WS] Client disconnected: {client_addr}")
        finally:
            self._clients.discard(websocket)

    @staticmethod
    async def handle_message(websocket: ServerConnection, message: str):
        """Handle incoming message from a client."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            await websocket.send(json.dumps({"error": "Invalid JSON"}))
            return

        action = data.get("action")
        if action == "subscribe":
            game_id = data.get("game_id")
            await websocket.send(json.dumps({"status": "subscribed", "game_id": game_id}))
            print(f"[WS] Client subscribed to game {game_id}")
        else:
            await websocket.send(json.dumps({"error": "Unknown action"}))

    async def broadcast_game_update(self, game_id: int, current_state: dict):
        if not self._clients:
            return

        message = {
            "type": "game_update",
            "game_id": game_id,
            "payload": current_state,
        }

        message_str = json.dumps(message)
        clients = tuple(self._clients)
        results = await asyncio.gather(
            *(client.send(message_str) for client in clients),
            return_exceptions=True,
        )
        sent_count = 0
        for client, result in zip(clients, results):
            if isinstance(result, ConnectionClosed):
                self._clients.discard(client)
            elif isinstance(result, BaseException):
                raise result
            else:
                sent_count += 1
        print(f"[WS] Broadcasted game {game_id} update to {sent_count} clients")

    async def start(self):
        """Start the WebSocket server."""
        self._server = await serve(self.handle_client, self.host, self.port)
        self._running = True
        print(f"[WS] Server started on ws://{self.host}:{self.port}")

        # graceful shutdown via signal
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._shutdown_event.set)

        # block until shutdown triggered
        await self._shutdown_event.wait()
        await self.stop()

    async def stop(self):
        """Stop the WebSocket server gracefully."""
        if not self._running:
            return

        print("[WS] Stopping server...")
        self._running = False

        # Close client connections
        await asyncio.gather(*(client.close() for client in self._clients), return_exceptions=True)
        self._clients.clear()

        # Stop the underlying server
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

        print("[WS] Server stopped cleanly.")
