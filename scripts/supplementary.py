"""Supplementary analyses run after the main pipeline (reads outputs/data/pools.json).

1. Game 1: exact Pareto frontier of (mean over scenarios, worst scenario) over ALL
   allocations, with and without the self-referential adversarial scenario.
2. Game 2: do the finalists depend on exact soldier counts of simulated opponents?
   Re-score them against holdout populations smoothed by random soldier moves.

The holdout populations are rebuilt with the dashboard's seeding, which
reproduces the main run's holdout populations exactly (seed 2026, 10,000).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from blotto import service  # noqa: E402
from blotto.config import DEFAULT_GAME, SimConfig  # noqa: E402
from blotto.generators import jitter  # noqa: E402
from blotto.vectorized import G2Field, all_allocations, g1_scores, g1_tables  # noqa: E402


def pareto(mean: np.ndarray, worst: np.ndarray, A: np.ndarray, n_points: int = 15) -> list[dict]:
    """Best mean subject to worst >= threshold, for thresholds spanning the attainable range."""
    out = []
    lo, hi = float(worst[np.argmax(mean)]), float(worst.max())
    for t in np.linspace(lo, hi, n_points):
        ok = worst >= t - 1e-9
        i = np.flatnonzero(ok)[np.argmax(mean[ok])]
        row = {"min_worst": float(t), "alloc": A[i].tolist(), "mean": float(mean[i]), "worst": float(worst[i])}
        if not out or out[-1]["alloc"] != row["alloc"]:
            out.append(row)
    return out


def main():
    sim = SimConfig()
    cfg = DEFAULT_GAME
    seed, n = sim.master_seed, sim.pop_size
    out = {}

    pops, notes = service.build_populations(cfg, "g1", n, seed, None, None)
    assert not notes, notes
    names = list(pops)
    A = all_allocations(cfg)
    S = np.stack([g1_scores(A, g1_tables(p.allocs, cfg)).astype(np.float32) for p in pops.values()], 1)
    indep = [i for i, nm in enumerate(names) if nm != "adversarial"]
    out["g1_pareto_all7"] = pareto(S.mean(1), S.min(1), A)
    out["g1_pareto_excl_adversarial"] = pareto(S[:, indep].mean(1), S[:, indep].min(1), A)
    for key in ("g1_pareto_all7", "g1_pareto_excl_adversarial"):
        for row in out[key]:
            i = int(np.flatnonzero((A == row["alloc"]).all(1))[0])
            row["scores"] = dict(zip(names, S[i].astype(float).round(4).tolist()))
    print("G1 frontier (all 7):")
    for r in out["g1_pareto_all7"]:
        print(f"  {r['alloc']}  mean {r['mean']:.3f}  worst {r['worst']:.3f}")

    R = json.loads((ROOT / "outputs" / "data" / "results.json").read_text())
    cands = [r["alloc"] for r in R["g2"]["ranked"][:4]] + [[0, 0, 40, 60, 0], [0, 0, 28, 0, 72], [0, 0, 40, 0, 60]]
    X = np.unique(np.array(cands), axis=0)
    pops2, notes = service.build_populations(cfg, "g2", n, seed, None, None)
    assert not notes, notes
    rng = np.random.default_rng(5)
    rows = {tuple(int(v) for v in x): {"raw": {}, "smoothed": {}} for x in X}
    for nm, p in pops2.items():
        for label, allocs in (("raw", p.allocs), ("smoothed", jitter(p.allocs, rng, 6))):
            ev = G2Field.from_population(allocs, rng, 200_000, cfg).evaluate(X)
            for i, x in enumerate(X):
                rows[tuple(int(v) for v in x)][label][nm] = [float(ev["mean"][i]), float(ev["se"][i])]
    table = []
    for x, d in rows.items():
        entry = {"alloc": list(x)}
        for label in ("raw", "smoothed"):
            m = np.array([v[0] for v in d[label].values()])
            entry[label] = {"scores": d[label], "mean": float(m.mean()), "worst": float(m.min()),
                            "balanced": float(0.5 * m.mean() + 0.5 * m.min())}
        table.append(entry)
    table.sort(key=lambda e: -e["smoothed"]["balanced"])
    out["g2_smoothing"] = table
    print("G2 smoothing test (balanced raw -> smoothed):")
    for e in table:
        print(f"  {e['alloc']}  raw {e['raw']['balanced']:.3f} (mean {e['raw']['mean']:.3f})  "
              f"smoothed {e['smoothed']['balanced']:.3f} (mean {e['smoothed']['mean']:.3f})")
    (ROOT / "outputs" / "data" / "supplementary.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
