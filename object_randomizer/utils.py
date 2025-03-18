import sys
from enum import Enum

sys.dont_write_bytecode = True


def constants_factory(offset, num_consts, prefix="CONST"):
    class Constants:
        __slots__ = tuple(f"{prefix}{i}" for i in range(num_consts))

        def __init__(self):
            for i in range(num_consts):
                setattr(self, f"{prefix}{i}", i + offset)

        def __str__(self) -> str:
            return f"r{self}"

        @property
        def size(self) -> int:
            return num_consts

    return Constants()


GRF = constants_factory(32, 256, 'r')


class XeEnum(Enum):
    def __str__(self) -> str:
        return self.name.lower()

    @property
    def v(self) -> int:
        return self.value

    @classmethod
    def keys(cls) -> list:
        return [e.value for e in cls]

    @classmethod
    def size(cls) -> int:
        return len(cls)
