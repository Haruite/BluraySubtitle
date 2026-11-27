from dataclasses import dataclass


@dataclass
class Event:
    def copy(self):
        """Copy the field mapping of an ASS event with immutable field values."""
        event = Event()
        event.__dict__ = self.__dict__.copy()
        return event

    def __repr__(self):
        return str(self.__dict__)


__all__ = ["Event"]
