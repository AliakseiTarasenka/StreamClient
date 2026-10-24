# API and WebSocket protocols

[Back to README](../README.md)

This document describes request construction and parser expectations in the repository. It is not an independently verified specification of the upstream scores service. Example payloads are synthetic.

## Upstream HTTP requests

All operations POST form data to `API_DEFAULT_URL`. The default content type is `application/x-www-form-urlencoded; charset=UTF-8`. HTTP errors are raised by `response.raise_for_status()`, and response text is passed to JSON parsers.

| Operation | Form fields |
| --- | --- |
| Schedule | `schedule=<YYYY-MM-DD>`, `date=<YYYY-MM-DD>` |
| Game snapshot | `game=<integer>`, `update=true`, `players=true`, `teams=true` |

The three `true` values are strings. APIClientPool caches responses by URL and sorted JSON representation of the request dictionary, with monotonic TTL expiry. Caching is enabled by default for both operations, including empty response bodies. Programmatic callers can use `post(data, use_cache=False)` or `invalidate_cache()`. HTTPS requests use normal HTTPX certificate verification.

### Schedule response

The parser expects an array. Empty or whitespace-only response text becomes an empty schedule. Invalid JSON or a JSON value other than an array raises ValueError. Entries missing required keys are skipped with a printed warning.

| API key | Game field | Required/default |
| --- | --- | --- |
| `i` | `game_id` | Required |
| `d` | `date` | Required |
| `t` | `time` | Required |
| `hn`, `ha` | `home_team`, `home_abbr` | Required |
| `an`, `aa` | `away_team`, `away_abbr` | Required |
| `h`, `a` | `home_score`, `away_score` | Default `"TBD"` |
| `e` | `is_finished` | Required; used by truthiness |
| `dv` | `division` | Required |

Schedule values are assigned without explicit conversion or schema validation.

```json
[
  {
    "i": 12345, "d": "2025-10-05", "t": "14:00",
    "hn": "Home Team", "ha": "HOME", "h": "0",
    "an": "Away Team", "aa": "AWAY", "a": "0",
    "e": false, "dv": "Open"
  }
]
```

### Game response

The parser expects an object containing these fields:

| API key | Interpretation | Default when missing |
| --- | --- | --- |
| `game_id` | Snapshot ID | `0`; the command does not inject the requested ID |
| `ts.time` | Accumulated time, interpreted by the clock as tenths of seconds | `None` |
| `ts.ds` | Stopwatch timestamp, divided by ten by the clock | `None` |
| `ts.stop` | Stopped flag; no boolean conversion | `true` |
| `h`, `a` | Home/away score, converted to strings | `"0"` |
| `hn`, `ha`, `an`, `aa` | Full team names and abbreviations | Empty strings |
| `p.h`, `p.a` | Roster maps keyed by string shirt number/player ID | Empty maps when keys are missing |
| `e` | Event array | Empty array |

Only events with `y == "S"` become GameEvent objects:

| Event key | Interpretation |
| --- | --- |
| `t` | Required integer timestamp; booleans are invalid |
| `e` | Required nonempty string team marker; `h` uses the home roster, all others use the away roster |
| `y` | Event type; only `S` is retained |
| `a`, `s` | Optional assister/scorer identifiers; converted to strings for roster lookup |
| `hs`, `as` | Event scores, converted to strings; missing values become empty strings |

Absent or unknown player identifiers produce None for the player name. File output substitutes a single space for unavailable latest scorer/assist names. The event with the greatest timestamp supplies latest names and, when nonempty, snapshot scores.

```json
{
  "game_id": 12345,
  "ts": {"time": 100, "ds": 0, "stop": true},
  "h": 1, "a": 0,
  "hn": "Home Team", "ha": "HOME",
  "an": "Away Team", "aa": "AWAY",
  "p": {"h": {"7": "Alex", "9": "Sam"}, "a": {}},
  "e": [{"t": 100, "e": "h", "y": "S", "a": 7, "s": 9, "hs": 1, "as": 0}]
}
```

Invalid JSON and malformed structures raise descriptive ValueError. The response, `ts`, `p`, and roster maps must be objects when supplied, roster names must be strings, `e` must be an array, and event items must be objects. Missing optional structures use defaults; explicitly supplied `ts: null`, `p: null`, roster null, or `e: null` are invalid. Scoring timestamps and team markers are validated before constructing events. Other timing/team fields retain the existing mapping without a full upstream schema.

## WebSocket interface

The optional server listens at `ws://<WEBSOCKET_HOST>:<WEBSOCKET_PORT>`, defaulting to `ws://localhost:8765`. It exchanges JSON text messages, including scoring-event objects. The [implementation report](review.md) records the serialization, subscription, retry, and lifecycle fixes.

### Client request and acknowledgment

```json
{"action": "subscribe", "game_id": 12345}
```

```json
{"status": "subscribed", "game_id": 12345}
```

Each connection selects one game. The ID must be a positive integer or an ASCII decimal string representing one; acknowledgments normalize it to an integer. Booleans, floats, missing/null IDs, nonpositive values, and malformed strings are invalid. Re-subscribing replaces the previous game. Only matching subscribers receive broadcasts. A subscription never starts monitoring: the CLI controls the monitored game. The browser's string IDs remain supported.

After acknowledgment, the server immediately sends the latest published snapshot for that game if one exists, even if it was published before any client connected. Otherwise the subscriber waits for the first published state. Cached snapshots and live broadcasts share an ordering boundary so replay cannot deliver older state after a newer broadcast. Cache contents clear on server stop.

| Invalid request | Response |
| --- | --- |
| Malformed JSON/encoding or decoder integer limit | `{"error": "Invalid JSON"}` |
| JSON array/scalar/null | `{"error": "Request must be a JSON object"}` |
| Unsupported/missing action | `{"error": "Unknown action"}` |
| Invalid/missing game ID for subscribe | `{"error": "Invalid game_id"}` |

These errors preserve the connection and any prior subscription. There is no authentication or per-game authorization; subscriptions provide routing only.

### Update envelope

The server constructs this envelope around GameState.to_dict(). Closed connections encountered during sends are removed without preventing other delivery. Unexpected send errors propagate after all selected sends complete. Individual sends have a five-second timeout; a programmatic constructor argument can override it.

```json
{
  "type": "game_update",
  "game_id": 12345,
  "payload": {
    "game_id": 12345,
    "game_time": 100,
    "game_stopwatch_timestamp": 0,
    "game_stopped": true,
    "home_score": "1",
    "away_score": "0",
    "teams": {
      "home_name": "Home Team", "home_abbr": "HOME",
      "away_name": "Away Team", "away_abbr": "AWAY"
    },
    "players": {"home": {"7": "Alex", "9": "Sam"}, "away": {}},
    "events": [
      {
        "event_time": 100, "team": "h", "event_type": "S",
        "assist": "Alex", "scorer": "Sam", "home_score": "1", "away_score": "0"
      }
    ],
    "latest_scorer": "Sam",
    "latest_assist": "Alex"
  }
}
```

Events always contain JSON objects with the seven fields shown above. Event scorer/assist and latest scorer/assist can be null when player lookup fails. Scores remain strings.

The outer game ID comes from the monitored ID; the payload ID comes from the upstream response and defaults to zero if missing. The monitor persists the fetched snapshot before publishing. Persistence and delivery checkpoints advance only after success; failed attempts invalidate their checkpoint so even a return to older state repairs partially updated outputs.

Unchanged failed delivery is retried. Newer fetched state can supersede an intermediate failed snapshot: this is latest-state output, not historical event replay. Partial send success can produce duplicates on retry; there is no client acknowledgment or exactly-once guarantee. Each fetch/persistence/delivery stage has its own budget: failures one through four delay by `poll_interval * (failure_count + 1)`, and the fifth propagates to the live supervisor. Every successful fetch resets fetch failures even when the response is unchanged. See [lifecycle.md](lifecycle.md) for cleanup behavior.
