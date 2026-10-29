"""Run every experiment and write outputs/data/*.json|csv, figures and REPORT.md.

    python scripts/run_all.py --quick        # smoke run (~minutes)
    python scripts/run_all.py                # full run
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from blotto.analysis import g1_analysis, g2_analysis  # noqa: E402
from blotto.config import DEFAULT_GAME, SimConfig  # noqa: E402
from blotto.pipeline import Log, jsonable, run_g1, run_g2  # noqa: E402


def write_csv(path: Path, ranked: list[dict], scen: list[str], game: str):
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        head = ["rank", "allocation", "total", "balanced", "mean_over_scenarios", "worst_case", "worst_scenario"]
        head += [f"score_{s}" for s in scen]
        if game == "g2":
            head += ["p_first", "p_second", "p_third", "p_fourth"]
        w.writerow(head)
        for r in ranked:
            row = [r["rank"], " ".join(map(str, r["alloc"])), r["total"], f"{r['balanced']:.4f}", f"{r['mean']:.4f}",
                   f"{r['worst']:.4f}", r["worst_scenario"]] + [f"{r['scenario_scores'][s]:.4f}" for s in scen]
            if game == "g2":
                row += [f"{p:.4f}" for p in r["detail_stated_mixture"]["pos"]]
            w.writerow(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "outputs"))
    ap.add_argument("--skip-g2", action="store_true")
    args = ap.parse_args()
    sim = SimConfig.quick() if args.quick else SimConfig()
    cfg = DEFAULT_GAME
    out = Path(args.out)
    (out / "data").mkdir(parents=True, exist_ok=True)
    log = Log()
    log(f"config: {'quick' if args.quick else 'full'} {sim.to_dict()}")

    g1 = run_g1(sim, cfg, log)
    with log.stage("G1 strategic analysis"):
        g1["analysis"] = g1_analysis(g1["_holdout"], np.array(g1["ranked"][0]["alloc"]), cfg)
    g2 = None
    if not args.skip_g2:
        g2 = run_g2(sim, cfg, log, g1_finalists=g1["_C"])
        with log.stage("G2 strategic analysis"):
            g2["analysis"] = g2_analysis(g2["_screen"], g2["_holdout"], np.array(g2["ranked"][0]["alloc"]),
                                         np.array(g1["ranked"][0]["alloc"]), np.random.default_rng(99),
                                         max(50_000, sim.g2_validate_groups // 2), cfg)

    meta = {"mode": "quick" if args.quick else "full", "sim": sim.to_dict(), "game": cfg.to_dict(),
            "python": platform.python_version(), "numpy": np.__version__, "platform": platform.platform(),
            "stages": log.stages, "total_seconds": round(time.perf_counter() - log.t0, 1),
            "peak_mb": round(log.peak_mb(), 1), "finished": time.strftime("%Y-%m-%d %H:%M:%S")}
    results = {"meta": meta, "g1": {k: v for k, v in g1.items() if not k.startswith("_")}}
    write_csv(out / "data" / "g1_ranked.csv", g1["ranked"], g1["scenario_names"], "g1")
    if g2:
        results["g2"] = {k: v for k, v in g2.items() if not k.startswith("_")}
        write_csv(out / "data" / "g2_ranked.csv", g2["ranked"], g2["scenario_names"], "g2")
        scr = g2["_screen"]
        np.savez_compressed(out / "data" / "g2_screen.npz", **{k: np.asarray(v) for k, v in scr.items()})
    # pools let the dashboard rebuild the same scenarios without recomputing optimizers
    pools = {"g1": {k: v for k, v in g1["_pools"].items()}}
    if g2:
        pools["g2"] = {k: v for k, v in g2["_pools"].items()}
    (out / "data" / "pools.json").write_text(json.dumps(jsonable(pools)))
    (out / "data" / "results.json").write_text(json.dumps(jsonable(results), indent=1))
    log(f"wrote results to {out / 'data'}")

    from blotto.plots import make_all
    from blotto.report import write_report
    with log.stage("figures"):
        make_all(results, out / "figures")
    write_report(results, out / "REPORT.md")
    if out.resolve() == (ROOT / "outputs").resolve():
        from publish_static import main as publish
        publish()
    log("all done")


if __name__ == "__main__":
    main()
