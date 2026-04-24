from dataclasses import dataclass


@dataclass
class Event:
    def __repr__(self):
        return str(self.__dict__)


__all__ = ["Event"]
