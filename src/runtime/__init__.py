"""Runtime/export entry modules."""


class TaskCancelled(Exception):
    """Stop the current worker or service without reporting an execution failure."""
