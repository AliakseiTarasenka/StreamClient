# Project review and implementation report

[Back to README](../README.md)

**Implemented and verified on 2026-10-24.** This report follows the original
2026-10-14 review and the subsequent verification against the working tree.
The required fixes are implemented. R1–R11 are resolved within their stated
scope; the remaining operational limits are listed separately below.

Three implementation agents divided HTTP/parsing, WebSocket transport/models,
and live persistence/retry work. A separate review pass by an agent examined the
combined changes. That review also led to fixes for HTTP cleanup masking primary
errors, existing loop signal ownership, and oversized numeric JSON input.
Integration review added regressions for partial output followed by an upstream
state reversal.

## Finding status

| Finding | Original problem | Implemented solution |
| --- | --- | --- |
| R1 | Wrong polling setting and unprotected startup | Composition uses settings.poll_interval; attempted starts and returned tasks remain protected by lifecycle cleanup. |
| R2 | GameEvent objects failed JSON serialization | Explicit event dictionaries in GameEvent.to_dict() and GameState.to_dict(). |
| R3 | Unsupported connection.open API | Supported asyncio WebSocket API retained; send results handled explicitly. |
| R4 | Starters returned before unsupervised services finished | Existing actual-task supervision, cancellation, and cleanup retained. |
| R5 | HTTPS verification disabled | HTTPX default certificate verification restored; local TLS rejection tested. |
| R6 | Failed broadcasts advanced delivered state; late subscribers had no snapshot | Independent delivery checkpoint, bounded retries, ordered snapshot replay and per-game subscriptions. |
| R7 | WebSocket mode skipped ten overlay files | Shared explicit persistence of the fetched snapshot in both live modes. |
| R8 | Placeholder and missing behavioral coverage | Placeholders replaced; HTTP/cache/parser/clock/live/WebSocket regressions added. |
| R9 | Non-object requests and invalid IDs crashed or were acknowledged | Defined validation errors, normalized positive IDs, usable connection after invalid input. |
| R10 | Unchanged successful fetches retained old fetch errors | Fetch failure count resets after every successful response. |
| R11 | Server-owned signal handlers survived shutdown | Scoped application signal ownership; custom/Runner/loop handlers preserved. |

## Architecture and SOLID implementation

[main.py](../main.py) remains the composition root. It constructs HTTP, file,
clock, monitor, and optional WebSocket implementations, adapts their lifecycle
callbacks, and closes the shared HTTP client. The CLI still depends only on
application query/session interfaces.

[Application ports](../src/application/ports.py) now also define GameAPI,
OverlayWriter, GameSnapshots, GameUpdatePublisher, and GameClock. Application
commands/services no longer import concrete HTTP or file implementations.
The monitor accepts snapshot/publisher contracts instead of concrete GameService
and WebSocketGameServer classes. The clock adapter accepts only its clock/writer
contracts. Infrastructure implements these structurally.

| Principle | Concrete application |
| --- | --- |
| Single responsibility | Parsers validate/map API data; PersistGameState maps snapshots to overlays; the monitor coordinates retries; the server handles subscriptions/delivery; ShutdownSignals handles process integration. |
| Open/closed | An alternative HTTP client, writer, publisher, or supervised service can satisfy the existing port/callback contracts without changing the coordinator. |
| Liskov substitution | Adapters honor async method signatures and error propagation; lifecycle starters return actual tasks, and stop tolerates partial startup. Deterministic fakes exercise the same contracts. |
| Interface segregation | CLI queries, snapshot operations, file writes, clock execution, and publishing each have focused interfaces; the monitor has no dependency on server startup or signal APIs. |
| Dependency inversion | Application behavior depends on application-owned Protocols; main.py supplies concrete infrastructure. |

The existing generic [LiveGameSession](../src/application/services/live_session.py)
continues to register every attempted start, supervise the returned tasks, end the
session on first completion, cancel/await registered work, and attempt every stop.
Cleanup errors cannot replace an existing service failure or cancellation.

## R2 — Scoring-event JSON serialization

**Changed:** [GameEvent](../src/domain/models/game_event.py) and
[GameState](../src/domain/models/game_state.py).

GameEvent.to_dict() explicitly returns event_time, team, event_type, assist,
scorer, home_score, and away_score. GameState maps its event list through that
method. Existing update-envelope fields and nested teams/players fields are
preserved. Unknown scorer/assist names serialize as JSON null; scores remain
strings. Domain models contain no WebSocket or HTTP implementation details.

**Verification:** a synthetic response with a scoring event is parsed, encoded,
broadcast over a real loopback connection, and replayed to a late subscriber.
The replay test also checks that later mutations of the caller's dictionary do
not alter the cached serialized snapshot. See
[WebSocket regressions](../tests/integration/test_websocket_server.py).

## R5 — Verified TLS and HTTP resource ownership

**Changed:** [API client/cache](../src/infrastructure/api/client.py) and
[main.py](../main.py).

The client no longer passes verify=False. Real requests use HTTPX's default TLS
verification. No insecure-mode setting or new custom-CA setting was added.
An optional keyword-only transport argument supports deterministic HTTP tests
without changing production transport selection.

main.py now passes REQUEST_TIMEOUT to APIClientPool. HTTP close is attempted on
construction/CLI failure and cancellation. A close failure is reported without
replacing an existing primary exception; on otherwise successful execution the
close failure propagates.

The cache now uses monotonic elapsed time for TTL, correctly returns cached empty
responses, and reports the full configured TTL without timedelta day wrapping.
Cache bypass still avoids reading/writing cache; failed HTTP responses are not
cached. The optional ResilientAPIClient retains bounded HTTP retries and lets
cancellation propagate.

**Verification:** [HTTP/cache tests](../tests/unit/test_api_client.py) cover form
fields/headers/timeouts, transport closure, hits, empty bodies, bypass,
invalidation, expiration, HTTP/connection errors, retry backoff/exhaustion, and
cancellation. A real local TLS listener with a self-signed fixture is rejected
with CERTIFICATE_VERIFY_FAILED. The fixture's private key is public test-only
material. [Main tests](../tests/unit/test_main.py) cover timeout wiring,
construction cleanup, and preservation of primary failures/cancellation.

## R6 and R10 — Independent output checkpoints and retry budgets

**Changed:** [GameEventStreamer](../src/infrastructure/websocket/streamer.py).

Each iteration fetches one GameState. A successful fetch resets the fetch-error
counter even when the snapshot is equal to the previous one. Persistence and
publication have independent counters and success checkpoints, so healthy fetches
cannot reset repeated output failures.

The monitor persists first and publishes only after persistence succeeds.
A delivered checkpoint advances only after publication succeeds. An unchanged
snapshot with failed delivery is attempted again, without repeating successful
WebSocket-mode persistence. On any write/send failure the corresponding
checkpoint is invalidated: if state changes A → B → A while B was partially
written/delivered, A is repaired/rebroadcast instead of being incorrectly skipped.

For each stage, failures one through four delay by
poll_interval × (failure_count + 1). The fifth failure raises the original error
to LiveGameSession, which stops sibling services. Cancellation interrupts the
backoff and propagates. Stop cancels/awaits the poll task and clears its active
game, task, persisted-state, and delivered-state entries.

Retries target the latest fetched snapshot; newer state can supersede an
intermediate failed update. This is a latest-state stream, not an event history.
After partial delivery, a retry may duplicate an update for healthy clients.
There is no client acknowledgment or exactly-once guarantee.

**Verification:** [monitor tests](../tests/unit/test_streamer.py) cover failed send
followed by unchanged state, independent write/send exhaustion, unchanged fetch
recovery, persistence before publication, A → B(partial failure) → A for both
outputs, file-only compatibility, and cancellation during a long backoff.
Existing [live-mode tests](../tests/integration/test_live_mode.py) retain
consecutive fetch exhaustion and sibling cleanup in both modes.

## R7 — Explicit shared snapshot persistence

**Changed:** [PersistGameState](../src/application/commands/persist_game_state.py),
[GameService](../src/application/services/game_service.py), and
[query commands](../src/application/commands/process_game.py).

PersistGameState owns the mapping of an already parsed GameState to the ten
existing overlay files. It depends only on OverlayWriter. Both the query command
and GameService.persist_game_state(state) reuse it. Persistence makes no HTTP
request, and the monitor no longer uses a hasattr-based optional hook.

Both live modes now maintain rosters, team names, scores, scorer, and assist.
File-only mode retains rewriting on every successful poll. WebSocket mode writes
changed or failed/pending snapshots, avoiding redundant successful writes while
retrying a send. The separate real clock continues to maintain clock.txt.

**Verification:** [HTTP-to-overlay integration tests](../tests/integration/test_integration.py)
assert all ten filenames and contents in query, file-only, and WebSocket modes,
with one upstream request per fetched snapshot. Explicit persistence is tested
without another fetch. The [composed live-output regression](../tests/integration/test_live_outputs.py)
runs the real service, clock, monitor, and local WebSocket server with HTTPX mock
responses: a late subscriber receives the first scoring snapshot, the next
snapshot updates files and the client, and normal server shutdown leaves no new
tasks or listener.

## R6 and R9 — Subscriptions, replay, validation, and transport lifecycle

**Changed:** [WebSocketGameServer](../src/infrastructure/websocket/server.py).

Each connection selects one positive game ID. Positive integer JSON values and
ASCII decimal strings are accepted and normalized to integer acknowledgments.
Booleans, floats, missing/null IDs, nonpositive values, and malformed strings are
rejected. Re-subscribing replaces the connection's prior game. A subscription
selects output; it never starts API polling, which remains CLI-controlled.

Invalid JSON/encoding and decoder integer-limit failures receive Invalid JSON;
non-object requests, unknown actions, and invalid IDs have their own defined
error responses. Invalid requests preserve the existing subscription and the
connection remains available for a subsequent valid request.

The server caches the latest serialized envelope per published game even with
no clients. A valid subscription receives its acknowledgment and then that
game's latest snapshot, if available. Subscription replay and live broadcasts
share a delivery lock, preventing an older replay from arriving after a newer
broadcast. Only matching subscribers receive broadcasts.

All selected sends run concurrently and are awaited before an unexpected failure
is raised. Closed peers are removed; other send failures propagate to the monitor.
Each send has a five-second timeout (constructor override for programmatic use).
A slow peer can delay the shared delivery lock up to the send timeout; this is a
deliberate simplicity tradeoff for the current single-game CLI.

The server owns no signal handlers. request_shutdown() requests normal completion.
Its start finalizer closes the listener/peers after normal shutdown, cancellation,
or failed startup. Cleanup failures preserve a primary failure/cancellation.
Stop clears subscriptions and replay state and supports subsequent reuse.

**Verification:** [loopback tests](../tests/integration/test_websocket_server.py)
cover scoring/null serialization, late replay, validation followed by valid
requests on the same socket, oversized numeric JSON, normalized strings,
per-game routing/re-subscription, replay/broadcast ordering, stale peers, partial
send failure, timeout without leaked send tasks, cancellation/reuse, bind failure,
and cleanup-error preservation. Protocol examples are in [protocols.md](protocols.md).

## R11 — Scoped application signals and cancellation

**Changed:** [ShutdownSignals](../src/infrastructure/signals.py) and
[main.py](../main.py).

main() wraps run_application() in a signal scope. Handlers are installed only
over default process handlers; existing custom, ignored, asyncio.Runner, and
event-loop-owned handlers retain ownership. This avoids a process handler and
an existing loop callback both cancelling the application.

Application-owned signals schedule one cancellation through call_soon_threadsafe;
repeated owned signals cannot interrupt cleanup again. Every installed handler
is restored on exit, including failure/cancellation. Restoration attempts all
handlers and preserves a primary exception. Unsupported/non-main-thread
registration leaves ordinary external task cancellation available.

Under ordinary asyncio.run(main()), Ctrl+C retains Runner's cancellation and
KeyboardInterrupt behavior. With default SIGTERM ownership, application-requested
cancellation finishes cleanup and main returns normally. External cancellation
continues to propagate. Embedded hosts retaining signals must arrange their own
shutdown/cancellation. No Unix-only loop.add_signal_handler call is required by
the application implementation.

**Verification:** [signal tests](../tests/unit/test_signals.py) and
[main tests](../tests/unit/test_main.py) cover restoration after all outcomes,
repeated/unsupported/partial registration, host/ignored ownership, primary-error
preservation, resource cleanup, and external cancellation. An isolated subprocess
sends real SIGTERM to verify that a pre-existing loop callback retains exclusive
ownership both inside and after the scope. Native Windows execution was not run.

## R8 — Behavioral coverage and parser contracts

The unit placeholder was removed and replaced by focused test modules. The
integration placeholder now exercises HTTP-to-overlay behavior. The suite has
grown from 27 cases/75% source coverage before these fixes to **95 cases/95%**.

[Event parsing](../src/application/parsers/event_parser.py) now reports descriptive
ValueError for invalid response, timing, player, roster, event-array/item shapes,
non-string roster names, missing/noninteger scoring timestamps, and empty/missing
team markers. Missing optional structures still default; explicitly supplied null
objects/arrays are invalid. Unknown player names remain None. Latest-event
selection still uses maximum timestamp; upstream units/order assumptions were
not changed without evidence.

[Parser tests](../tests/unit/test_parsers.py) cover both rosters, scoring mappings,
out-of-order events, score fallback, unknown players, malformed input, and schedule
mapping/defaults/skipped entries. [Clock tests](../tests/unit/test_game_clock.py)
use controlled time for tenths conversion, stopped/running countdown, repeated
wall-clock ticks, five-second refresh boundaries, zero clamp, and cancellation.

The expanded make test-live includes signals, main cleanup, deterministic clock,
monitor retries, query/output integration, composed live outputs, and WebSocket
regressions with warnings treated as errors. No dependency or tool was added.

## Verification on 2026-10-24

Local Python 3.12.3, HTTPX 0.28.1, websockets 15.0.1, pytest 8.4.2.
The locked environment was synchronized with uv sync --locked.

| Check | Result |
| --- | --- |
| make ci | Passed: Black (51 files), project-wide Flake8 hook, Pylint (9.93/10 with diagnostics), MyPy (36 source files), and all 95 source-coverage tests. |
| make test-live | 62 cases passed with warnings treated as errors. |
| python -m pytest tests/ -q -W error | 95 cases passed. |
| Source coverage | 95% overall; event parser, monitor, snapshot persistence, and signal module 100%; HTTP/cache 99%. |
| uv pip check | All 51 installed packages compatible. |
| Agent review | Earlier actionable findings fixed; final review found no blockers. |

Pylint still reports lower-priority diagnostics in existing schedule parsing,
clock complexity, file-manager import order, and GameState attribute count,
plus legacy configuration warnings. A passing score is not a claim of zero
diagnostics. Exact current totals are from the final local verification, not
GitHub-hosted CI.

Tests use HTTPX mocks, controlled time, temporary output, local TLS/WebSocket
listeners, and isolated process signals. No remote scores API request was sent
and real overlay output was not used.

## Remaining limits and optional follow-up

- Overlay writes remain sequential and non-atomic; a crash can leave a partial
  multi-file snapshot. No multi-process writer lock or per-game namespace was
  introduced. Use one live writer per output directory.
- Deliveries are latest-state, may duplicate after partial success, and have no
  client receipt acknowledgment. Subscriptions are routing, not authorization;
  the server still has no authentication.
- Replay storage and HTTP cache are in-memory and unbounded by game/key count;
  replay clears at server stop and expired HTTP entries are removed on access.
  This is suitable for the current single-game CLI, not a general multi-game host.
- Five-second cache TTL can mask changes across two-second polls; configure TTL
  deliberately. The clock still uses wall time and existing tenths-of-seconds
  upstream assumptions, which require real upstream fixtures for independent
  confirmation.
- Logging settings and API_DEFAULT_ENV remain unused. Numeric settings still
  lack positive/range constraints. REQUEST_TIMEOUT is now effective.
- Native Windows execution, browser interaction, remote TLS compatibility, and
  real tournament data were not tested. A previously accepted untrusted remote
  certificate will now fail until the deployment's trust configuration is fixed.
- The historical requirements.txt requests mismatch remains resolved; dependency
  inputs/lock were not changed by this implementation. No clean pip reinstall or
  GitHub-hosted CI run was performed.
