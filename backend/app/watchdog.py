"""A timer thread that stops a piece of work when it takes too long.

Power of Ten rule 2 asks that every loop has a fixed upper bound. Work we hand
to other software (a SQL query, a child process) has no loop of ours to bound,
so we bound it in time instead: a watchdog waits for the work to finish and,
if the time limit passes first, stops it.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import override

from app.invariants import require


class Watchdog(threading.Thread, ABC):
    """Calls `on_timeout()` unless `finish()` is called within `timeout_s` seconds.

    Subclasses decide what "stop the work" means by implementing `on_timeout`.
    Use it like this::

        watchdog = SomeWatchdog(...)
        watchdog.start()
        try:
            do_the_work()
        finally:
            timed_out = watchdog.finish()
    """

    def __init__(self, name: str, timeout_s: float) -> None:
        require(timeout_s > 0, f"timeout must be positive, got {timeout_s}")
        super().__init__(name=name, daemon=True)
        self._timeout_s = timeout_s
        self._finished = threading.Event()
        self._fired = threading.Event()

    @override
    def run(self) -> None:
        if not self._finished.wait(self._timeout_s):
            self._fired.set()
            self.on_timeout()

    @abstractmethod
    def on_timeout(self) -> None:
        """Stop the work. Called from the watchdog thread."""

    def finish(self) -> bool:
        """Mark the work as done and wait for the thread to end.

        Returns:
            True if the time limit was reached before the work finished.
        """
        self._finished.set()
        self.join()
        return self._fired.is_set()
