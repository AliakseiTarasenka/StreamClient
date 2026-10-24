# Development and verification

[Back to README](../README.md)

## Local commands

Install and activate the environment using the [setup instructions](../README.md#setup). Metadata and dependency groups are in [pyproject.toml](../pyproject.toml), with resolved versions in [uv.lock](../uv.lock). The pip installation path uses [requirements.txt](../requirements.txt).

```bash
# Existing tests and coverage.
make test

# Lifecycle, construction cleanup, clock/polling, and WebSocket regressions.
# Warnings are treated as errors; no coverage report is generated.
make test-live

# Flake8 pre-commit hook and Pylint with repository configuration.
make lint

# MyPy with the same command used in GitHub Actions.
make typecheck

# Apply Black formatting; modifies Python files.
make format

# Check formatting without changing files.
make format-check

# Formatting check, lint, type checking, and the full test suite.
make ci
```

`make test-live` selects the session, main, signal, clock, and monitor unit tests,
plus query/persistence, live-mode, composed live-output, and WebSocket integration
tests. Its 62 cases check partial startup, resource cleanup, signal ownership,
controlled clock behavior, fetch/output retries, snapshot reversions, scoring
delivery/replay, and shutdown using temporary directories and loopback connections.

## Pre-commit and CI style checks

Install the development environment with `uv sync --locked` (or install requirements.txt in an activated virtual environment), then enable the Git hook once per checkout:

```bash
pre-commit install
pre-commit run --all-files
```

[.pre-commit-config.yaml](../.pre-commit-config.yaml) runs the exact project-wide command `flake8 src/ tests/ config/ main.py --max-line-length=100`. It uses an isolated Python environment with Flake8 7.4.1, passes no additional filenames, and runs even when only non-Python files change. CI invokes the same hook with `pre-commit run --all-files --show-diff-on-failure`.

`make lint` runs the shared Flake8 pre-commit hook and Pylint. `make format` only applies Black formatting. `make ci` runs the read-only format check, lint checks, MyPy through `make typecheck`, and tests in sequence; it does not rewrite source files. This matches GitHub Actions' source quality and test checks; GitHub Actions also checks installed dependencies and exports coverage as XML. All Make targets are declared phony so files named after a target cannot skip its checks.

The [CI workflow](../.github/workflows/ci.yml) runs for pull requests targeting main on Python 3.12. Its quality job checks Black formatting, runs the Flake8 pre-commit hook, and checks Pylint/MyPy results. Its dependent test job runs pytest with source coverage. Flake8, pre-commit, and MyPy are declared in the development dependency group and requirements.txt. The test job adds pytest-asyncio to the same dependency-install command. Both jobs run pip check after installation.

The hook's Flake8 version matches requirements.txt and the current uv.lock. When upgrading Flake8, update the hook pin and both dependency inputs together.

## MyPy dependency compatibility

MyPy 2.4.0 requires pathspec >=1.0.0. The previous workflow installed a current MyPy first and then installed requirements.txt, which downgraded pathspec to 0.12.1. This reproduced `ModuleNotFoundError: No module named 'pathspec.patterns.gitignore'` before type checking began. The `--ignore-missing-imports` flag does not fix missing dependencies of MyPy itself.

The development group, requirements.txt, and uv.lock now select MyPy 2.4.0 and pathspec 1.1.1. CI installs each job's dependencies in one resolver pass and checks the result, preventing the old two-step downgrade. After `uv sync --locked`, the equivalent local checks are:

```bash
python -m pip check
python -m mypy src/ config/ main.py --ignore-missing-imports
```

If uv created the environment without pip, use `uv pip check` instead of `python -m pip check`. Current verification: no broken dependencies, MyPy reports no issues in 36 source files, Black and the Flake8 hook pass, and all 95 tests pass with warnings treated as errors. Existing annotation errors exposed after fixing the import crash were corrected without suppressing MyPy diagnostics.

## Existing tests

The original suite had two `assert True` placeholders and 0% source coverage.
The unit placeholder was removed in favor of focused modules; the integration
placeholder now tests the actual HTTP-to-overlay path. The current suite has
95 cases and 95% source coverage.

| Tests | Behavioral coverage |
| --- | --- |
| [HTTP/cache](../tests/unit/test_api_client.py) | Forms/headers/timeouts, resource closure, cache hit/empty body/bypass/expiry/invalidation, HTTP/connection retry/exhaustion/cancellation, real self-signed local TLS rejection. |
| [Parsers](../tests/unit/test_parsers.py) | Scoring/rosters/unknown players, ordering and score fallback, malformed structures, schedule fields/defaults/skipped entries. |
| [CLI](../tests/unit/test_cli.py) | Seven query/live routing, precedence, error-display, and cancellation cases using application interfaces. |
| [Session](../tests/unit/test_live_session.py) | Seven partial-start/runtime/cleanup cases; actual task completion checked before loop shutdown. |
| [Main](../tests/unit/test_main.py) and [signals](../tests/unit/test_signals.py) | Construction/HTTP cleanup, effective timeout, primary-error preservation, signal restoration/host ownership/unsupported registration, isolated real loop-owned SIGTERM. |
| [Clock](../tests/unit/test_game_clock.py) | Controlled tenths conversion, stopped/running countdown, duplicate ticks, refresh boundaries, zero clamp, cancellation. |
| [Monitor](../tests/unit/test_streamer.py) | Independent retry budgets, unchanged-state recovery, persistence before publication, A→B(partial failure)→A repair, rewrite compatibility, backoff cancellation. |
| [Query/output integration](../tests/integration/test_integration.py) | All ten overlay filenames/contents with scoring snapshots in query and both live modes, without duplicate fetches. |
| [Live lifecycle](../tests/integration/test_live_mode.py) | Repeated file updates, clock/fetch/WebSocket failures, sibling cleanup, normal server shutdown. |
| [Composed live output](../tests/integration/test_live_outputs.py) | Real clock/monitor/server with mocked HTTP, repeated scoring overlays, late replay, delivery, and task/listener cleanup. |
| [WebSocket](../tests/integration/test_websocket_server.py) | Real delivery, stale/failed peers, scoring/null serialization, immutable replay, routing/validation/order, bounded sends, cancellation/reuse/bind failure. |

Tests use asyncio.run() and require no pytest-asyncio plugin. TLS fixtures in
tests/fixtures/tls contain a public test-only certificate/private key and never
authenticate a deployment. Tests do not contact the remote scores API or write
real overlay output. Native Windows and browser interaction were not verified.

## Review validation

This section retains the **historical** review and earlier implementation checks.
For the 2026-10-24 fixes, current checks, and remaining limits, see the
[implementation report](review.md#verification-on-2026-10-24).

The documentation review used Python 3.12.3, HTTPX 0.28.1, websockets 15.0.1, pytest 8.4.2, and uv 0.9.2 from the local environment.

| Check | Result |
| --- | --- |
| `uv sync --locked --dry-run --offline` | Lock resolved without changing the environment |
| CLI argument parser `--help` | Advertised game, date, and start options |
| `python -m pytest tests/ -v --cov=src` | Two placeholder tests passed; 0% source coverage |
| Synthetic game response through persistence command | Parsed scores/names and wrote ten expected files in a temporary directory |
| Default `Settings(_env_file=None)` | poll_interval exists; polling_interval does not |
| JSON encoding GameState.to_dict() | Empty events serialize; a GameEvent raises TypeError |
| Loopback WebSocket connection and subscribe message | Subscription acknowledgment received |
| Broadcast over that connection | AttributeError: connection has no .open attribute |
| CLI coordination with mocked starters and a polling alias | Returned and called cleanup immediately without a WebSocket task |

Focused checks were temporary review probes, not additions to the test suite. No requests were sent to the remote scores API. Remote availability, clock units, real event data, browser behavior, and full CI checks were not validated.

The table records the original documentation review. Following the R3 implementation, the broadcast failure is resolved and covered by committed regression tests. The changed server passes Pylint and both changed Python files pass Black's formatting check.

R1's follow-up also protects starter task creation with cleanup and adds regression tests. The changed CLI passes Pylint; the CLI and its regression tests pass Black's formatting check. Settings and APIConfig now use model_config with SettingsConfigDict, removing the Pydantic class-based configuration deprecation warnings.

R4 supervises the returned clock and polling tasks alongside the WebSocket server. After the SOLID refactor, LiveGameSession owns supervision and the CLI delegates through an application Protocol. Verification uses `python -m pytest tests/ -v -W error`; all 27 cases pass. The changed presentation, application interfaces/session, and composition root pass Pylint, and changed Python files pass Black's formatting check. See the [lifecycle guide](lifecycle.md) for startup/shutdown behavior and asyncio semantics.

## Follow-up validation priorities

The 2026-10-24 implementation covers synthetic field mapping, unknown players,
malformed structures, cache expiration, scoring-event output, independent retries,
and unchanged-state recovery. Future validation should focus on real upstream
fixtures for clock units/event ordering, native platform/browser behavior, and any
chosen persistence-consistency guarantees. Keep automated checks deterministic
and independent of a live tournament.

Keep protocol examples synchronized with [protocols.md](protocols.md), settings with [.env.example](../.env.example), and behavior changes with the [review report](review.md).
