import sys

import pandas as pd

from field import Field, FieldType
from rand_object import RandObject

sys.dont_write_bytecode = True


class BaseFormat(RandObject):

    def __init__(self, fmt, fmt_width, instr, seed=None):
        super().__init__(fmt, seed)
        self._bitwidth = fmt_width
        self._instr = instr
        self._fields = {}

    def __str__(self):
        return f"{self._instr}_{super().__str__()}"

    def add_fields(self, **kwargs):
        for field, value in kwargs.items():
            self._fields[field] = Field(name=field, **value)
            fobj = self._fields[field]

            if field in ['dbg', 'uip', 'jip', 'cip', 'msgd']:
                fobj.set_rand_mode(False)

            if fobj.ftype != FieldType.IMPLIED:
                self.addVariable(fobj.name, fobj.domain)

    def print(self):
        data = {}
        for field in self._fields.items():
            if getattr(field[1], 'ftype', None) == FieldType.VIRTUAL:
                continue
            data[field[0]] = field[1].value
        # dataframe from dictionary
        df = pd.DataFrame(data, index=[0]).T.rename(columns={0: 'Value'})
        print(df.to_markdown() + '\n')

    def _pre_randomize(self, **kwargs):
        for key, val in kwargs.items():
            if key in self._fields:
                if isinstance(val, range) or isinstance(val, list):
                    self.addConstraint(lambda x, v=val: x in v, (key,))
                else:
                    self.addConstraint(lambda x, v=val: x in [v], (key,))

    def _post_randomize(self):
        for field, fobj in self._fields.items():
            if field in self._solution:
                fobj.set_value(self._solution[field])

    def randomize(self, **kwargs) -> None:
        self._randomize(**kwargs)

    def encode(self) -> int:
        value = 0

        # iterate over fields and set the final value
        for field in self._fields.values():
            if field.ftype == FieldType.VIRTUAL:
                continue
            value |= field.get_pos_value(self._bitwidth)

        # iterate over virtual fields and resolve the value
        for field in self._fields.values():
            if field.ftype == FieldType.VIRTUAL:
                cfield = self._fields[field.cfield]
                if cfield.value == field.cvalue:
                    # clear the bits
                    value &= ~(field.mask << field.start)
                    # set the bits
                    value |= field.get_pos_value(self._bitwidth)

        return value

    @property
    def hex(self) -> str:
        return hex(self.encode())[2:].zfill(self._bitwidth // 4)

    @property
    def bytes(self) -> bytes:
        return bytes.fromhex(self.hex)[::-1]
