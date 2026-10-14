"""Start, supervise, and stop a group of services for one live game."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceLifecycle:
    """Adapt a service to the session's common lifecycle contract.

    start returns the actual running task. stop must be safe after partial startup.
    """

    name: str
    start: Callable[[int, int], Awaitable[asyncio.Task[None]]]
    stop: Callable[[int], Awaitable[None]]


class LiveGameSession:
    """Supervise injected services without depending on their implementations."""

    def __init__(
        self,
        services: Sequence[ServiceLifecycle],
        report_error: Callable[[str], None] = print,
    ):
        if not services:
            raise ValueError("A live session requires at least one service")
        self._services = tuple(services)
        self._report_error = report_error

    async def run(self, game_id: int, duration_minutes: int) -> None:
        """Run until a service finishes, fails, or the caller cancels the session."""
        tasks: list[asyncio.Task[None]] = []
        attempted: list[ServiceLifecycle] = []
        primary_error: BaseException | None = None
        try:
            for service in self._services:
                # Include a partially started service in cleanup if start raises.
                attempted.append(service)
                task = await service.start(game_id, duration_minutes)
                tasks.append(task)
            await self._wait_for_completion(tasks)
        except BaseException as error:
            primary_error = error
            raise
        finally:
            await self._shutdown(tasks, attempted, game_id, primary_error)

    @staticmethod
    async def _wait_for_completion(tasks: Sequence[asyncio.Task[None]]) -> None:
        """Observe the first completion and propagate any completed-task failure."""
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in tasks:
            if task in done:
                task.result()

    async def _shutdown(
        self,
        tasks: Sequence[asyncio.Task[None]],
        services: Sequence[ServiceLifecycle],
        game_id: int,
        primary_error: BaseException | None,
    ) -> None:
        """Finish every task and stop call before reporting cleanup failures."""
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        results = await asyncio.gather(
            *(self._stop_service(service, game_id) for service in services), return_exceptions=True
        )
        errors = []
        for service, result in zip(services, results):
            if isinstance(result, BaseException):
                errors.append(result)
                self._report_error(f"Error stopping {service.name}: {result}")
        if primary_error is None and errors:
            raise errors[0]

    @staticmethod
    async def _stop_service(service: ServiceLifecycle, game_id: int) -> None:
        """Capture errors from calling a stop adapter as well as awaiting it."""
        await service.stop(game_id)
