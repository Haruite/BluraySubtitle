"""Shared cancellation sentinel for runtime services."""


class _Cancelled(Exception):
    pass

