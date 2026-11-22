"""Checks that stay switched on in production (Power of Ten rule 5).

Python removes every `assert` statement when it runs with the `-O` flag, so app
code does not rely on `assert`. `require()` always runs. When a check fails it
raises `InvariantError`. That is a bug in our code, not bad input from a user,
so the caller does not try to "fix" it: the error surfaces and gets reported.

Input from users and from the AI model is checked separately, with ordinary
errors such as `DatasetError` that the API turns into helpful messages.
"""

from __future__ import annotations


class InvariantError(RuntimeError):
    """A condition that must always hold did not hold."""


def require(condition: bool, message: str) -> None:
    """Raise `InvariantError(message)` unless `condition` is true.

    Args:
        condition: A side-effect-free test, such as `0 < limit <= MAX_ROWS`.
        message: What went wrong, written for the developer who reads the error.

    Raises:
        InvariantError: If `condition` is false.
    """
    if not condition:
        raise InvariantError(message)
