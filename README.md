# StreamClient

StreamClient is a Python command-line application for retrieving Ultimate Frisbee schedules and game events from the scores API at `scores.frisbee.pl`. It writes team information, rosters, scores, and scoring players to text files for livestream overlays. It also contains a countdown clock, an optional WebSocket server, and a small browser client.

The application uses asyncio, HTTPX, Pydantic Settings, aiofiles, and websockets. The entry point is [main.py](main.py).

## Current status

Schedule retrieval, game queries, and continuous file-only monitoring are implemented. Startup cleanup (R1), WebSocket connection compatibility (R3), and live-task supervision (R4) are fixed and covered by regression tests. Remaining findings in the [review report](docs/review.md) include scoring-event serialization and broadcast retry behavior.

## Setup

Use Python 3.12 or newer; [.python-version](.python-version) selects 3.12. Run commands from the repository root. With uv installed:

```bash
git clone https://github.com/AliakseiTarasenka/StreamClient.git
cd StreamClient
uv sync --locked
source .venv/bin/activate
```

If using pip instead of uv:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell. The WebSocket server's signal handling currently assumes a Unix event loop.

Create local configuration only if `.env` does not already exist:

```bash
cp -n .env.example .env
```

Edit `API_DEFAULT_URL` to select the required scores endpoint. The template supplies the default test endpoint from the code; its availability and data were not verified against the remote service. See the [configuration reference](docs/configuration.md) for all settings and their effective behavior.

## Usage

```bash
# Show command-line help.
python main.py --help

# Print the schedule for a date.
python main.py --date 2025-10-05

# Print scoring events and save overlay files for a game.
python main.py --game 12345
```

Replace the example date and game ID with values for your event. A schedule query prints each game's ID, date, start time, teams, scores, division, and finished status. A game query prints team scores and scoring events, and overwrites the files listed below.

`--game` takes precedence when both `--game` and `--date` are supplied. `--start` only takes effect with a truthy game ID. With no game or date, the CLI prints an error and returns without an explicit nonzero exit status. Dates are passed through without format validation.

### Live monitoring

```bash
# Continuously update overlay files and the countdown clock.
python main.py --game 12345 --start
```

Live mode stays active until cancellation, a service finishes, or a service fails. Clock errors and exhausted polling retries terminate the session and propagate the error after cleanup. Press Ctrl+C to stop file-only monitoring.

Set `ENABLE_WEBSOCKET=true` to also start a WebSocket server at `ws://localhost:8765`; its normal shutdown stops the clock and polling too. Scoring-event serialization (R2), broadcast retries (R6), and overlay snapshot persistence with WebSocket enabled (R7) still need the fixes described in the [review report](docs/review.md).

The example browser UI is [client/ws-client.html](client/ws-client.html). Once the live-mode defects are resolved and the server is running, open it in a browser, enter the monitored game ID, and click **Fetch Game**. The JavaScript connects to a hardcoded `ws://localhost:8765`; entering a game ID sends a subscription acknowledgment request and does not start API monitoring for that game.

## Overlay files

`OUTPUT_PATH` defaults to `output`, relative to the process working directory. Files use UTF-8 and are replaced on each persisted snapshot.

| File | Contents |
| --- | --- |
| `home_roster.txt`, `away_roster.txt` | One `player_id: player_name` entry per line |
| `home_name.txt`, `away_name.txt` | Team abbreviations |
| `home_name_full.txt`, `away_name_full.txt` | Full team names |
| `home_score.txt`, `away_score.txt` | Current scores as text |
| `scorer.txt`, `assist.txt` | Latest scorer and assister names; a single space if unavailable |
| `clock.txt` | Remaining time in `MM:SS`, written by the clock task in live mode |

A single `--game` query writes ten files, excluding `clock.txt`. WebSocket monitoring currently skips those ten overlay files; only the separate clock task writes `clock.txt`. Files have fixed names, so multiple games or processes sharing the same output directory overwrite each other's data. Writes are sequential and not atomic; consumers can observe partial updates.

## Development and documentation

```bash
python -m pytest tests/ -v --cov=src
```

The suite has 27 cases covering CLI routing, lifecycle contracts, resource cleanup, repeated overlay snapshots, runtime failures, and WebSocket shutdown. Scoring-event delivery and the remote API still need further validation.

- [Architecture and execution flow](docs/architecture.md)
- [SOLID design and service lifecycle: startup, shutdown, wait, and gather](docs/lifecycle.md)
- [Environment configuration](docs/configuration.md)
- [Upstream API and WebSocket protocol](docs/protocols.md)
- [Development workflow and verification](docs/development.md)
- [Project review and prioritized findings](docs/review.md)

## License

[MIT](LICENSE).
