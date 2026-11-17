"""Runtime/export entry modules."""

import sys
from multiprocessing import get_context


class TaskCancelled(Exception):
    """Stop the current worker or service without reporting an execution failure."""


def worker_process_context():
    # The Ubuntu bundle uses fork to start workers from its frozen interpreter.
    if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
        return get_context("fork")
    return get_context("spawn")
