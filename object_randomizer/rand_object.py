
import random
import sys
from datetime import datetime

from constraint import Problem

sys.dont_write_bytecode = True


class RandObject(Problem):
    __instance_count = 0

    def __init__(self, name, seed=None):
        super().__init__()
        self._instance_id = RandObject.__instance_count
        RandObject.__instance_count += 1
        self._name = name
        self._seed = seed or datetime.now().timestamp()
        self._random_calls = 0
        self._solution = None

    def __str__(self):
        return self._name

    def _install_seed(self):
        self._random_calls += 1
        return random.Random(self._seed + self._instance_id + self._random_calls)

    def _pre_randomize(self, **kwargs):
        pass

    def _post_randomize(self):
        pass

    def _randomize(self, **kwargs):
        self._pre_randomize(**kwargs)

        rand = self._install_seed()
        domains, constraints, vconstraints = self._getArgs()
        if domains is None:
            raise ValueError("No domains specified")

        for var in domains:
            rand.shuffle(domains[var])
        self._solution = self._solver.getSolution(domains, constraints, vconstraints)

        if self._solution is None:
            raise ValueError("No solution found")

        self._post_randomize()
