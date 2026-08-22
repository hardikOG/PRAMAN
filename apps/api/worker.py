"""Background worker process.

Owns everything that must run outside the request/response cycle: consuming
the S3 behaviour-signal stream from Redis, expiring step-up tokens past their
TTL, and retrying failed webhook deliveries with backoff (Phases 4/6). Phase 0
wires only the process shape and its healthcheck contract: touch a heartbeat
file each cycle so `docker-compose.yml`'s healthcheck can tell "running" from
"wedged" without depending on Postgres/Redis being reachable yet.
"""

from __future__ import annotations

import asyncio
import contextlib
import pathlib
import signal

from apps.api.config import get_settings
from apps.api.logging import configure_logging, get_logger

HEARTBEAT_PATH = pathlib.Path("/tmp/worker_alive")
HEARTBEAT_INTERVAL_SECONDS = 10

logger = get_logger(__name__)


async def _heartbeat_loop(stop_event: asyncio.Event) -> None:
    """Touch the heartbeat file until `stop_event` is set.

    Inputs: `stop_event` — set on SIGTERM/SIGINT to unwind the loop cleanly.
    Outputs: none; side effect is writing to `HEARTBEAT_PATH`.
    Complexity: O(1) per cycle.
    Failure cases: a filesystem error propagates and crashes the worker,
        which is intentional — the healthcheck should then correctly fail.
    """
    while not stop_event.is_set():
        HEARTBEAT_PATH.touch()
        logger.info("praman.worker.heartbeat")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS)


async def main() -> None:
    """Run the worker until asked to stop.

    Real queue consumption (behaviour stream, webhook retry, step-up expiry)
    is added alongside the stages that produce that work (Phases 4 and 6).
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("praman.worker.startup", env=settings.praman_env)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await _heartbeat_loop(stop_event)
    logger.info("praman.worker.shutdown")


if __name__ == "__main__":
    asyncio.run(main())
