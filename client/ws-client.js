const log = (msg) => {
  const pre = document.getElementById("log");
  pre.textContent += msg + "\n";
  pre.scrollTop = pre.scrollHeight;
};

let ws = null;

document.getElementById("fetchBtn").addEventListener("click", () => {
  const gameId = document.getElementById("game_id").value.trim();
  if (!gameId) return alert("Please enter a game ID");

  // Close previous connection if it exists
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.close();
  }

  // Create new WebSocket connection
  ws = new WebSocket("ws://localhost:8765");

  ws.onopen = () => {
    log(`✅ Connected to WebSocket server`);
    ws.send(JSON.stringify({ action: "subscribe", game_id: gameId }));
    log(`➡️ Subscribed to game_id: ${gameId}`);
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "game_update" && data.game_id == gameId) {
      log(`📡 Game ${data.game_id} update:`);
      log(JSON.stringify(data.payload, null, 2));
    } else {
      log("ℹ️ " + JSON.stringify(data));
    }
  };

  ws.onclose = () => log("❌ Disconnected");
  ws.onerror = (err) => log("⚠️ Error: " + err.message);
});
