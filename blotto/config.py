"""Game rules and experiment configuration.

Every rule is a parameter so the dashboard can change castle values, payouts
and soldier totals; the defaults are the confirmed Restart rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np

# Castle points are split among at most 4 tied players, so multiplying all
# castle values by lcm(1, 2, 3, 4) = 12 keeps every score an exact integer.
SCALE = 12


@dataclass(frozen=True)
class GameConfig:
    values: tuple[int, ...] = (1, 2, 3, 4, 5)
    soldiers: int = 100
    payouts: tuple[float, ...] = (9.0, 4.0, 2.0, 0.0)

    def __post_init__(self):
        if len(self.values) < 1 or any(int(v) != v or v < 0 for v in self.values):
            raise ValueError("castle values must be nonnegative integers")
        if int(self.soldiers) != self.soldiers or self.soldiers < 0:
            raise ValueError("soldiers must be a nonnegative integer")
        if len(self.payouts) != 4:
            raise ValueError("four-way game needs exactly 4 placement payouts")

    @property
    def n_castles(self) -> int:
        return len(self.values)

    @property
    def total_points(self) -> int:
        return int(sum(self.values))

    @property
    def total_payout(self) -> float:
        return float(sum(self.payouts))

    @property
    def values_arr(self) -> np.ndarray:
        return np.asarray(self.values, dtype=np.int64)

    @property
    def cum_payouts(self) -> np.ndarray:
        """S[k] = sum of the top-k payouts, with S[0] = 0."""
        return np.concatenate([[0.0], np.cumsum(np.asarray(self.payouts, dtype=float))])

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_GAME = GameConfig()


@dataclass
class SimConfig:
    """Experiment sizes. `quick()` shrinks everything for smoke runs."""

    pop_size: int = 10_000            # opponents per scenario (train and holdout each)
    n_random_candidates: int = 5_000  # random-search / G2 screening candidates
    g2_screen_groups: int = 20_000    # CRN opponent triples used while optimizing G2
    g2_validate_groups: int = 200_000 # fresh triples per scenario for finalist validation
    evo_generations: int = 60
    evo_pop: int = 200
    evo_restarts: int = 4
    selfplay_iters: int = 40
    seeds: tuple[int, ...] = (11, 23, 37)
    master_seed: int = 2026
    n_finalists: int = 25
    sensitivity_draws: int = 200

    @classmethod
    def quick(cls) -> "SimConfig":
        return cls(pop_size=2_000, n_random_candidates=600, g2_screen_groups=3_000,
                   g2_validate_groups=20_000, evo_generations=12, evo_pop=60,
                   evo_restarts=2, selfplay_iters=8, seeds=(11, 23), n_finalists=10,
                   sensitivity_draws=40)

    def to_dict(self) -> dict:
        return asdict(self)
