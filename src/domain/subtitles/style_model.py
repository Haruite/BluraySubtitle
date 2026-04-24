from dataclasses import dataclass


@dataclass
class Style:
    def __repr__(self):
        return str(self.__dict__)


__all__ = ["Style"]
