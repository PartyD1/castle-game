"""Hypothetical applicant populations.

None of these scenarios is claimed to be the real applicant pool.  They are
transparent mixtures of the generator families so that recommendations can
be stress-tested against very different assumptions.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import DEFAULT_GAME, GameConfig
from .generators import NAIVE_FAMILIES, POOL_FAMILIES, from_pool, generate
from .optimize.best_response import g1_best_response_dp, g1_top_k, g2_best_response
from .optimize.self_play import g1_fictitious_play, g2_fictitious_play
from .vectorized import g1_tables

# Mixture weights per scenario (normalized at sampling time).  "adversary" is a
# pool family filled with best responses to the current candidate finalists.
SCENARIOS: dict[str, dict[str, float]] = {
    "balanced": {"equal": 0.40, "noisy_heuristic": 0.20, "rounded": 0.15,
                 "dirichlet": 0.10, "proportional": 0.15},
    "proportional": {"proportional": 0.50, "noisy_heuristic": 0.20, "rounded": 0.15,
                     "equal": 0.05, "dirichlet": 0.10},
    "concentrated": {"high_value": 0.35, "middle": 0.20, "low_value": 0.15,
                     "dirichlet": 0.15, "rounded": 0.15},
    "random": {"uniform_random": 0.50, "dirichlet": 0.40, "noisy_heuristic": 0.10},
    "strategic": {"strategic": 0.40, "best_response": 0.25, "self_play": 0.20,
                  "noisy_heuristic": 0.15},
    "broad_mixture": {"equal": 0.08, "proportional": 0.12, "high_value": 0.08, "middle": 0.06,
                      "low_value": 0.05, "uniform_random": 0.08, "dirichlet": 0.10,
                      "noisy_heuristic": 0.15, "rounded": 0.10, "strategic": 0.08,
                      "best_response": 0.05, "self_play": 0.05},
    "adversarial": {"adversary": 0.50, "strategic": 0.15, "noisy_heuristic": 0.15,
                    "proportional": 0.10, "equal": 0.10},
}
SCENARIO_DESCRIPTIONS = {
    "balanced": "Mostly equal-split and near-equal intuitive allocations.",
    "proportional": "Mostly allocations proportional to castle value, with noise and rounding.",
    "concentrated": "Mostly players who concentrate on a few castles (high, middle or low).",
    "random": "Mostly uniform-random and Dirichlet-random allocations.",
    "strategic": "Mostly computationally optimized players (best responses and self-play outputs).",
    "broad_mixture": "A broad mix of every family; the stated default mixture for averaging.",
    "adversarial": "Half best responses targeting the candidate finalists, plus strategic and simple players.",
}
NAIVE_SCENARIOS = ("balanced", "proportional", "concentrated", "random")


@dataclass
class Population:
    allocs: np.ndarray   # (n, C)
    labels: np.ndarray   # (n,) family names
    scenario: str

    def __len__(self):
        return len(self.allocs)


def sample_population(weights: dict[str, float], n: int, rng: np.random.Generator,
                      pools: dict[str, np.ndarray] | None = None, cfg: GameConfig = DEFAULT_GAME,
                      name: str = "custom") -> Population:
    pools = pools or {}
    fams = [f for f, w in weights.items() if w > 0]
    w = np.array([weights[f] for f in fams], dtype=float)
    counts = rng.multinomial(n, w / w.sum())
    parts, labels = [], []
    for fam, c in zip(fams, counts):
        if c == 0:
            continue
        if fam in POOL_FAMILIES or fam == "adversary":
            if fam not in pools or len(pools[fam]) == 0:
                raise ValueError(f"family {fam!r} requires a computed pool")
            x = from_pool(rng, c, cfg, pool=pools[fam])
        else:
            x = generate(fam, rng, c, cfg)
        parts.append(x)
        labels += [fam] * c
    return Population(np.concatenate(parts), np.array(labels), name)


def naive_reference(rng: np.random.Generator, n: int, cfg: GameConfig = DEFAULT_GAME) -> np.ndarray:
    """An evenly weighted mixture of the naive families (no computed pools)."""
    return sample_population({f: 1.0 for f in NAIVE_FAMILIES}, n, rng, cfg=cfg).allocs


def build_pools(game: str, rng: np.random.Generator, cfg: GameConfig = DEFAULT_GAME,
                n_ref: int = 4000, selfplay_iters: int = 30, g2_groups: int = 4000) -> dict[str, np.ndarray]:
    """Compute the strategic / best-response / self-play pools for one game.

    strategic:     optimized responses to each naive scenario and the naive mixture
    best_response: optimized responses to each single naive family
    self_play:     fictitious-play best responses starting from the naive mixture
    """
    targets = {s: sample_population(SCENARIOS[s], n_ref, rng, cfg=cfg).allocs for s in NAIVE_SCENARIOS}
    targets["naive_mix"] = naive_reference(rng, n_ref, cfg)
    fam_targets = {f: generate(f, rng, n_ref, cfg) for f in NAIVE_FAMILIES}
    if game == "g1":
        strategic = np.concatenate([g1_top_k(g1_tables(t, cfg), 60, cfg)[0] for t in targets.values()])
        br = np.concatenate([g1_top_k(g1_tables(t, cfg), 20, cfg)[0] for t in fam_targets.values()])
        sp = np.array(g1_fictitious_play(targets["naive_mix"], selfplay_iters, cfg=cfg)["best_responses"])
    elif game == "g2":
        strategic = np.concatenate([g2_best_response(t, rng, cfg, groups=g2_groups).top[:15]
                                    for t in targets.values()])
        br = np.concatenate([g2_best_response(t, rng, cfg, groups=g2_groups, generations=15).top[:6]
                             for t in fam_targets.values()])
        sp = np.array(g2_fictitious_play(targets["naive_mix"], rng, max(4, selfplay_iters // 3),
                                         groups=g2_groups, cfg=cfg)["best_responses"])
    else:
        raise ValueError("game must be 'g1' or 'g2'")
    return {"strategic": np.unique(strategic, axis=0), "best_response": np.unique(br, axis=0),
            "self_play": np.unique(sp, axis=0)}


def adversary_pool_g1(finalists: np.ndarray, cfg: GameConfig = DEFAULT_GAME, k: int = 15) -> np.ndarray:
    """Exact best responses against each finalist and against the finalists as a group."""
    out = [g1_top_k(g1_tables(finalists, cfg), 3 * k, cfg)[0]]
    for f in finalists:
        out.append(g1_top_k(g1_tables(f[None], cfg), k, cfg)[0])
    return np.unique(np.concatenate(out), axis=0)


def adversary_pool_g2(finalists: np.ndarray, rng: np.random.Generator, cfg: GameConfig = DEFAULT_GAME,
                      background: np.ndarray | None = None, groups: int = 3000) -> np.ndarray:
    """Game 2 responses tuned to fields where the finalists are common.

    A field made only of finalists, and a field of finalists mixed 50/50 with a
    background population, are each attacked with the G2 optimizer.
    """
    fields = [finalists[rng.integers(0, len(finalists), 600)]]
    if background is not None:
        fields.append(np.concatenate([finalists[rng.integers(0, len(finalists), 600)],
                                      background[rng.integers(0, len(background), 600)]]))
    out = [g2_best_response(f, rng, cfg, groups=groups, generations=20).top[:15] for f in fields]
    return np.unique(np.concatenate(out), axis=0)


def scenario_seed(master: int, scenario: str, split: str, game: str) -> int:
    """Deterministic, distinct seeds per (scenario, split, game)."""
    names = list(SCENARIOS)
    return int(np.random.SeedSequence([master, names.index(scenario), ["train", "holdout"].index(split),
                                       ["g1", "g2"].index(game)]).generate_state(1)[0])


def build_scenarios(game: str, pools: dict[str, np.ndarray], n: int, master: int, split: str,
                    cfg: GameConfig = DEFAULT_GAME, include=None) -> dict[str, Population]:
    out = {}
    for name, w in SCENARIOS.items():
        if include is not None and name not in include:
            continue
        if "adversary" in w and "adversary" not in pools:
            continue
        rng = np.random.default_rng(scenario_seed(master, name, split, game))
        out[name] = sample_population(w, n, rng, pools, cfg, name)
    return out
