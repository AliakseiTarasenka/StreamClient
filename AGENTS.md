# StreamClient project guidance

StreamClient is an asyncio CLI that retrieves Ultimate Frisbee schedules and game
events, writes text files for livestream overlays, and optionally broadcasts game
updates over WebSocket. Run commands from the repository root.

## Setup and tooling

- Use Python 3.12 for parity with `.python-version` and CI.
- Install the locked environment with `uv sync --locked`, then activate it with
  `source .venv/bin/activate`. Alternatively, create a Python 3.12 virtual
  environment and run `python -m pip install -r requirements.txt`.
- If local configuration is needed, copy `.env.example` only when `.env` is
  absent. Preserve existing configuration and user changes.
- Use the existing tools: Black with a 100-character line length, Flake8 through
  pre-commit, Pylint, MyPy, and pytest. Avoid adding tools or dependencies for
  routine changes. Keep dependency inputs and `uv.lock` consistent when changing
  dependencies.

## Architecture boundaries

- `main.py` constructs concrete dependencies, owns the HTTP client's lifetime,
  and scopes application signal handling while preserving existing host handlers.
- `src/presentation/` handles CLI arguments, command routing, and displayed output;
  it depends on the application interfaces in `src/application/ports.py`.
- `src/application/` contains use cases, parsers, query interfaces, and services.
  Commands and services depend on the focused Protocols in `ports.py`, not
  concrete infrastructure. `LiveGameSession` supervises services through
  `ServiceLifecycle` callbacks.
- `src/domain/` contains game models; keep infrastructure concerns out of models.
- `src/infrastructure/` implements HTTP/cache access, overlay file persistence,
  polling, and WebSocket transport. `config/` supplies settings, and `client/`
  contains the static browser demo.
- Preserve externally consumed overlay filenames and protocol fields unless the
  requested change requires updating their contracts and documentation.

## Async lifecycle rules

- A lifecycle start callback returns the actual scheduled task. Record attempted
  starts before invoking them so partial initialization is cleaned up.
- Supervise running tasks, propagate failures and cancellation, and end the live
  session when any service finishes. File-only monitoring must stay active while
  its services run, independently of WebSocket support.
- During shutdown, cancel and await every registered task and attempt every
  started or partially started service's cleanup. Cleanup errors must not replace
  the primary exception or cancellation.
- Close HTTP clients, WebSocket connections, and listeners. Avoid blocking work on
  the event loop. Verify task cleanup before event-loop shutdown so `asyncio.run()`
  does not hide leaked tasks.

## Code Review Rules

These rules apply repository-wide. Review the changed behavior and its callers,
using the architecture, lifecycle, and protocol guides below as context. Verify
historical findings in `docs/review.md` against the current implementation.

### Findings and evidence

- Prioritize correctness, security, data loss, task/resource leaks, and externally
  visible regressions. Report actionable issues introduced or worsened by the
  change, with priority, the smallest useful file/line location, the triggering
  scenario, user impact, and a suggested correction. Explain assumptions when
  the failure depends on specific input or timing; do not present guesses as facts.
- Check SOLID through concrete responsibilities and application Protocol
  contracts. Flag dependencies that move transport/file concerns into domain
  models or couple application behavior to concrete infrastructure. Concrete
  construction in `main.py` is intentional. Avoid speculative abstractions,
  cosmetic refactors, and findings already enforced by formatting/lint checks.

### Async lifecycle and ownership

- Flag startup paths that lose a scheduled task or omit cleanup after partial
  initialization. Verify file-only mode stays active, failures/cancellation reach
  the supervisor, and every registered task is cancelled and awaited before
  shutdown completes. Cleanup must attempt all resources and preserve the primary
  exception; a cleanup failure propagates when there is no primary error.
- Check closure of HTTP clients, WebSocket peers/listeners, and bounded send/retry
  work. Flag blocking I/O on the event loop. Signal integration belongs at the
  application boundary: preserve custom/ignored/Runner/loop-owned handlers and
  restore handlers installed by the application, including on failure.

### Snapshot persistence and delivery

- Both live modes must maintain the ten overlay snapshot files and the separate
  clock output. Persist the already fetched snapshot before publication; do not
  fetch again solely to persist it. Preserve consumed filenames and contents
  unless a deliberate contract change includes updated consumers/documentation.
- Persistence and delivery checkpoints advance only after their operation
  succeeds. Partial failures must invalidate the affected checkpoint so a state
  reversal also repairs output. Successful unchanged fetches reset fetch errors;
  fetch, persistence, and delivery failures retain independent bounded budgets.
- Latest-state coalescing and duplicate sends after partial success are supported
  behavior. Sequential non-atomic files are a documented limit. Report changes
  that worsen these guarantees or contradict a new promise, rather than treating
  the existing limits as newly introduced defects.

### Input, protocol, and HTTP contracts

- Verify scoring events and unknown players remain JSON-compatible, envelope
  fields and score types stay compatible, and malformed requests receive defined
  errors without corrupting a valid subscription. Check positive normalized game
  IDs, matching-game routing, and acknowledgment/replay/live-update ordering.
  Subscribing selects output; it must not silently start API monitoring.
- Preserve default TLS certificate verification. Check that HTTP failures are
  raised and not cached, TTL expiry uses elapsed monotonic time, and bypass and
  empty-response caching retain their contracts. New/changed settings must affect
  the advertised behavior; dependency inputs and the lock must remain consistent.
- Validate malformed upstream structures explicitly while preserving documented
  defaults and unknown-player handling. Do not assume different upstream clock
  units or event ordering without fixtures or other evidence.

### Behavioral verification

- Look for focused regressions covering the concrete failure being fixed,
  including partial startup, cancellation, unchanged snapshots, partial output,
  or late subscribers when relevant. Prefer deterministic HTTP mocks, controlled
  time, temporary directories, and real loopback WebSocket/TLS behavior over
  placeholders or assertions that only mirror implementation details.
- For lifecycle changes, assertions must check cleanup while the loop is still
  running. Identify the missing scenario when coverage is inadequate. Follow the
  verification commands below and report only checks actually run; documentation
  changes alone do not require the Python runtime suite.

## Verification

- `make format-check`: check Black formatting without modifying source.
- `make lint`: run the project-wide Flake8 pre-commit hook and Pylint.
- `make typecheck`: run `python -m mypy src/ config/ main.py --ignore-missing-imports`.
- `make test`: run the full test suite with source coverage.
- `make test-live`: run lifecycle, construction cleanup, clock/polling, and
  WebSocket regression tests with warnings treated as errors (`-W error`).
- `make ci`: run formatting, lint, type checking, and the full test suite in order.
- `make format` rewrites Python files; use it intentionally.

Run checks appropriate to the change; use `make test-live` for lifecycle or
WebSocket work and `make ci` before declaring a code change ready. Use deterministic
HTTP mocks, temporary output directories, and loopback WebSocket connections for
tests. Do not rely on a live tournament or overwrite real overlay output during
verification. Report the checks actually run and any failures or limits.

## Reference documentation

- [README and setup](README.md)
- [Architecture and execution flow](docs/architecture.md)
- [Service lifecycle and cancellation contracts](docs/lifecycle.md)
- [API and WebSocket protocol](docs/protocols.md)
- [Configuration](docs/configuration.md)
- [Development workflow](docs/development.md)
- [Review findings](docs/review.md): verify findings against current code; this
  report includes resolved historical issues.

Update relevant documentation when behavior, settings, or protocol contracts
change. Project-specific Codex agents and usage examples are in
[`.codex/agents/`](.codex/agents/README.md).
