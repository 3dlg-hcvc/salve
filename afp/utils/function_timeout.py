

"""Utility to execute a process for a limited amount of allowed execution time.

Reference: https://stackoverflow.com/questions/2281850/timeout-function-if-it-takes-too-long-to-finish
"""

import signal
import time

import pytest


class timeout:
    def __init__(self, seconds: int = 1, error_message: str = "Timeout") -> None:
        """ """
        self.seconds = seconds
        self.error_message = error_message

    def handle_timeout(self, signum: int, frame) -> None:
        """ """
        raise TimeoutError(self.error_message)

    def __enter__(self) -> None:
        signal.signal(signal.SIGALRM, self.handle_timeout)
        signal.alarm(self.seconds)

    def __exit__(self, type, value, traceback) -> None:
        """ """
        signal.alarm(0)


def test_timeout() -> None:
    """Ensure that timeout decorator/scope works properly."""
    # should time out
    with pytest.raises(TimeoutError):
        with timeout(seconds=3):
            time.sleep(4)

    # should not time out
    with timeout(seconds=5):
        time.sleep(4)


if __name__ == "__main__":
    test_timeout()