# Configuration reference

[Back to README](../README.md)

Configuration is loaded separately by [Settings](../config/settings.py) and [APIConfig](../src/infrastructure/api/config.py). Both locate `.env` at the repository root using their source paths, read UTF-8, match declared field names without case sensitivity, and allow extra fields.

For normal startup, process environment variables override `.env` values, which override class defaults. Programmatic constructor arguments take precedence over those sources. No environment-variable prefix is required.

## Application settings

| Environment variable | Type | Default | Effective behavior |
| --- | --- | --- | --- |
| `MAX_CONNECTIONS` | Integer | `100` | HTTPX maximum total connections; keepalive limit is fixed at 20 |
| `CACHE_TTL` | Integer | `5` | API response cache lifetime, in seconds |
| `REQUEST_TIMEOUT` | Integer | `30` | Passed by `main.py` to the shared HTTP client's timeout, in seconds |
| `ENABLE_WEBSOCKET` | Boolean | `false` | Constructs a server; started only by `--game … --start` |
| `WEBSOCKET_HOST` | String | `localhost` | WebSocket listening address |
| `WEBSOCKET_PORT` | Integer | `8765` | WebSocket port |
| `POLL_INTERVAL` | Integer | `2` | Polling interval in seconds; passed to the streamer by the CLI |
| `OUTPUT_PATH` | String | `output` | Text-file directory; relative paths resolve from the process working directory |
| `GAME_DURATION` | Integer | `25` | Clock duration in minutes |
| `LOG_LEVEL` | String | `INFO` | Declared but unused; diagnostics use `print()` |
| `LOG_FORMAT` | String | `json` | Declared but unused; output is plain text |

Pydantic validates declared field types, but no positive-value constraints are defined for duration, intervals, connection limits, or ports. Invalid field types fail during configuration loading.

## API settings

| Environment variable | Type | Default | Effective behavior |
| --- | --- | --- | --- |
| `API_DEFAULT_URL` | String | `https://scores.frisbee.pl/test3/ext/watchlive.php/` | Target for every HTTP POST |
| `API_DEFAULT_HEADERS` | JSON encoded as a string | `{"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}` | Parsed by `json.loads()` when loading headers |
| `API_DEFAULT_ENV` | String | `test` | Stored but unused; does not select or change the URL |

Header values must be a JSON object suitable for HTTPX. There is no explicit schema validation of the decoded headers. Changing `API_DEFAULT_ENV` alone leaves the endpoint unchanged.

## Example

[.env.example](../.env.example) supplies defaults for the implemented query modes. For a one-off override on a Unix shell:

```bash
OUTPUT_PATH=/tmp/streamclient-output python main.py --game 12345
```

Keep local endpoint choices in `.env`, which is already ignored by Git. The template contains code defaults rather than values copied from a local `.env`.

## Operational behavior

- `AsyncFileManager` creates the output directory during startup, even for schedule and help invocations.
- TLS certificate verification uses HTTPX defaults and is enabled. There is no insecure-mode or application-specific custom-CA setting; private CA deployments must configure trust normally. See [review.md](review.md), finding R5.
- The CLI instantiates `APIClientPool`, which does not retry HTTP failures. `ResilientAPIClient` exists for programmatic use but is not selected by a setting.
- Live polling and clock requests share one cache with monotonic TTL expiry. A two-second poll can receive the same response until the five-second TTL expires. Expired entries are removed on access; the cache has no size limit or background cleanup.
- Monitor fetch, persistence, and delivery each have a five-failure budget; failures one through four back off by `POLL_INTERVAL * (failure_count + 1)`. The fifth raises to the session. The WebSocket server bounds each send to five seconds (programmatic constructor override; no environment setting).
- The WebSocket server owns no process signals. The application scope preserves custom/ignored handlers, including asyncio.Runner's Ctrl+C and existing loop handlers; it temporarily installs cancellation handlers over defaults. Unsupported registration leaves external task cancellation available.
- `POLLING_INTERVAL` is not a declared setting. The CLI now uses `POLL_INTERVAL`; the original mismatch is recorded as R1 in the review. Extra `.env` fields do not receive declared-field type validation.
