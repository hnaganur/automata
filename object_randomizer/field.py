import sys
from enum import Enum
from typing import Any

import random
from pydantic import BaseModel, PrivateAttr

sys.dont_write_bytecode = True


class FieldType(Enum):
    DEFAULT = 0
    IMPLIED = 1
    VIRTUAL = 2


class Field(BaseModel):
    # User attributes
    name: str
    values: list = None
    start: int
    end: int
    default: int = -1
    cfield: str = None  # type: ignore
    cvalue: int = 0
    ftype: FieldType = FieldType.DEFAULT

    # Internal attributes
    _size: int = PrivateAttr()
    _mask: int = PrivateAttr()
    _value: int = PrivateAttr()
    _rand_mode: bool = PrivateAttr(default=True)

    def __init__(self, **data: Any):
        if 'ftype' in data:
            data['ftype'] = FieldType[data['ftype'].upper()]
        super().__init__(**data)

    # Internal methods
    def model_post_init(self, __context: Any) -> None:
        self._size = self.end - self.start + 1
        self._mask = (1 << self._size) - 1
        self._value = self.default

        if self.ftype == FieldType.IMPLIED:
            self._rand_mode = False

    def __str__(self) -> str:
        return self.name

    @property
    def rand_mode(self) -> bool:
        return self._rand_mode

    @property
    def size(self) -> int:
        return self._size

    @property
    def mask(self) -> int:
        return self._mask

    @property
    def value(self) -> int:
        return self._value

    @property
    def domain(self):
        if self.rand_mode:
            if self.values:
                return self.values

            if self.size > 16:
                sample = [random.randint(0, (1 << self.size) - 1) for _ in range(1000)]
                return sample
            return range(1 << self.size)
        return [self.default]

    def set_rand_mode(self, mode: bool) -> None:
        self._rand_mode = mode

    def set_value(self, value: int) -> None:
        self._value = value

    def set_domain(self, domain: list) -> None:
        if isinstance(domain, range):
            self.values = list(domain)
        else:
            self.values = domain

    def get_pos_value(self, format_bits: int):
        format_mask = (1 << format_bits) - 1
        return ((self.value & self.mask) << self.start) & format_mask
