# CLI design and service lifecycle

[Back to README](../README.md)

The refactor separates command-line presentation, service lifecycle management, and construction of concrete dependencies. The 2026-10-24 implementation extends application Protocols to API, file, snapshot, publisher, and clock operations, adds independent output retry checkpoints, and moves signal ownership out of the server. R1/R4 cleanup guarantees are retained. The injected CLI constructor accepts a live session instead of a WebSocket server.

## Responsibilities and SOLID

| Principle | Application in this project |
| --- | --- |
| Single responsibility | CLIHandler handles presentation, LiveGameSession supervises services, PersistGameState maps files, the monitor coordinates retries, the server handles transport/subscriptions, and main.py composes them. |
| Open/closed | LiveGameSession works with a sequence of ServiceLifecycle adapters. Adding a service means registering another adapter; the supervision and shutdown algorithms stay the same. |
| Liskov substitution | Query/session implementations can be replaced when they honor the declared contracts. A lifecycle start callback must return the actual scheduled Task; its stop callback must tolerate partial startup. |
| Interface segregation | GameQueries/LiveSession serve the CLI; GameAPI, OverlayWriter, GameSnapshots, GameUpdatePublisher, and GameClock expose focused operations for their consumers. Lifecycle adapters expose only a name and start/stop callbacks. |
| Dependency inversion | Application commands/services and the monitor depend on application Protocols. The session depends on callable contracts; main.py supplies concrete implementations and application signal integration. |

[ports.py](../src/application/ports.py) uses typing.Protocol for structural interfaces: implementations satisfy the interface by providing matching methods, without inheriting from it. Python does not enforce these type hints at runtime. See the [Python Protocol documentation](https://docs.python.org/3.12/library/typing.html#typing.Protocol).

The output function is also injected into CLIHandler, making routing and displayed messages testable without replacing global print(). Explicit argv can be passed to handle() or parse_arguments(); omitting it reads the process command line as before.

## Construction versus startup

[main.py](../main.py) loads settings, creates the HTTP client and file manager, and constructs the query service. create_live_session() constructs the clock and monitor, and registers adapters in this order:

1. Clock.
2. WebSocket server, if enabled.
3. Game monitor.

Constructing these objects does not start their live loops or bind the WebSocket socket. The file manager still creates its output directory during construction.

Schedule queries and single game queries only call the query interface. They do not call LiveSession.run(), so the clock, polling loop, and WebSocket server do not start. main.py closes the shared HTTP client after CLI execution, including when dependency construction or command execution fails.

## Starting a live game

For `--game 12345 --start`, CLIHandler calls the injected session's run(12345, game_duration). [LiveGameSession](../src/application/services/live_session.py) then:

1. Records a service as attempted before calling start(), so partial initialization is included in cleanup.
2. Awaits its start callback and stores the returned Task.
3. Repeats for each registered service.
4. Waits for any running task to finish.

Clock.start() and monitor.start_monitoring() already schedule their loops with create_task() and return those tasks. The WebSocket adapter schedules server.start(), whose coroutine runs until shutdown. Awaiting a start callback waits for task registration; it does not await the whole game or guarantee that the WebSocket socket is already listening.

The loops execute concurrently on the asyncio event loop. They yield while waiting for network responses, file operations, or timers; this does not imply one operating-system thread per service.

## When services stop

The session ends when a service finishes normally, a running task fails, startup fails, or the caller cancels the session. In file-only mode, both loops normally run indefinitely, so Ctrl+C is the usual shutdown trigger. Reaching zero on the clock does not itself finish the clock task.

The server has no signal handlers. Calling request_shutdown() closes its connections and listener and finishes its task normally; the session observes that completion and stops the clock and monitor too. A failed clock task or exhausted fetch/persistence/delivery retry budget also ends the session and propagates the error.

main() scopes ShutdownSignals around run_application(). It installs cancellation handlers only over default process handlers and restores installed handlers on every exit. Custom/ignored signals, asyncio.Runner's SIGINT, and existing event-loop callbacks retain host ownership. Owned signals schedule cancellation only once, allowing cleanup to finish. With normal asyncio.run(main()), Ctrl+C retains Runner's cancellation/KeyboardInterrupt behavior. Default SIGTERM uses application-requested cancellation and main returns normally after cleanup. External cancellation still propagates. Non-main-thread/unsupported registration relies on external cancellation; embedded hosts retaining signals must arrange their own shutdown. Native Windows execution has not been verified.

Shutdown always runs in finally:

1. Request cancellation of every registered task. Cancelling an already completed task has no effect.
2. Await all registered tasks so their cancellation and finalizers finish.
3. Run every attempted service's stop callback, including the service whose start failed.
4. Inspect cleanup errors after all stop calls finish.

Stop methods release service state and resources: the monitor removes game/task/persistence/delivery checkpoints, the clock clears its running state, and the WebSocket server closes its connections/listener and clears subscriptions/replay. The shared HTTP client closes separately in main.py; close failures preserve an existing primary failure/cancellation, and propagate when there is no primary error.

If a runtime failure or cancellation caused shutdown, cleanup errors are reported without replacing that primary exception. Without a primary exception, the first cleanup failure is raised after all stop calls have finished.

## wait(), gather(), and cancellation

| Operation | Purpose here |
| --- | --- |
| create_task(coroutine) | Schedule a coroutine and obtain the Task representing its execution. |
| wait(tasks, return_when=FIRST_COMPLETED) | Return the done and pending task sets when any task finishes or is cancelled. It does not cancel pending tasks or raise a task's exception. |
| task.result() | Read an already completed task's outcome; raise its failure or cancellation if present. |
| task.cancel() | Request cancellation. The coroutine must get a chance to handle it and run its finally blocks. |
| gather(*tasks, return_exceptions=True) | Await every registered task during shutdown and collect failures/cancellations as results. |
| gather(*stop_calls, return_exceptions=True) | Schedule stop coroutines concurrently and await every result, so one cleanup failure cannot prevent the others from running. |

gather() returns results in input order, even when work finishes in a different order. Its default return_exceptions=False propagates the first exception immediately; the other submitted work is not automatically cancelled. With return_exceptions=True, individual failures become result values, which this session explicitly inspects. Cancelling gather itself still cancels unfinished submitted work. These semantics are documented in the [Python asyncio reference](https://docs.python.org/3.12/library/asyncio-task.html#asyncio.gather).

The session uses wait() while running because it must react to the first service completion. It uses gather() while stopping because cleanup must finish for every service. gather() alone does not stop infinite loops: cancellation is requested first.

## Verification and remaining limits

Tests cover command routing, lifecycle contracts, partial startup at each position, runtime failure, cancellation, cleanup failure, signal restoration/host ownership, controlled clock timing, output retries and state reversions, both overlay modes, scoring delivery/replay, validation, timeouts, and real server shutdown. make test-live selects 62 cases with warnings treated as errors; the full suite has 95 passing cases. Sequential/non-atomic files, duplicate/latest-only delivery, native platform verification, and other limits are recorded in the [implementation report](review.md).
