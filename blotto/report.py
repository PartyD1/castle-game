"""Write outputs/REPORT.md from results.json.

All numbers are generated from the results file.  Hand-written conclusions
(final comparison and application response) live in outputs/narrative.md and
are included verbatim when present, so they can be revised after reading the
data without touching the generated tables.
"""
from __future__ import annotations

from pathlib import Path


def _a(x):
    return "[" + ", ".join(map(str, x)) + "]"


def _f(x, d=3):
    return f"{x:.{d}f}"


def _table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    out += ["| " + " | ".join(map(str, r)) + " |" for r in rows]
    return "\n".join(out)


def _scenarios(G):
    names = G["scenario_names"]
    rows = [[n, G["scenario_descriptions"][n],
             ", ".join(f"{k} {v:.2f}" for k, v in G["scenario_weights"][n].items())] for n in names]
    return _table(["scenario", "description", "mixture weights"], rows)


def _ranked_table(G, game, k=10):
    names = G["scenario_names"]
    head = ["#", "allocation", "total", "balanced", "mean", "worst (scenario)"] + names
    if game == "g2":
        head += ["P(1st/2nd/3rd/4th)"]
    rows = []
    for r in G["ranked"][:k]:
        row = [r["rank"], _a(r["alloc"]), r["total"], _f(r["balanced"]), _f(r["mean"]),
               f"{_f(r['worst'])} ({r['worst_scenario']})"] + [_f(r["scenario_scores"][n]) for n in names]
        if game == "g2":
            row.append(" / ".join(f"{p:.2f}" for p in r["detail_stated_mixture"]["pos"]))
        rows.append(row)
    return _table(head, rows)


def _sw_table(G, k=10):
    rows = [[r["rank"], _a(r["alloc"]), r["strengths"], r["vulnerabilities"]] for r in G["ranked"][:k]]
    return _table(["#", "allocation", "main strengths", "main vulnerabilities"], rows)


def _castle_table(G, k=5):
    rows = []
    for r in G["ranked"][:k]:
        d = r["detail_stated_mixture"]
        rows.append([r["rank"], _a(r["alloc"])] + [f"{w:.2f}/{t:.2f}" for w, t in zip(d["castle_win"], d["castle_tie"])])
    return _table(["#", "allocation"] + [f"C{c} win/tie" for c in range(1, 6)], rows)


def _family_table(G, k=5):
    fams = sorted(G["ranked"][0]["detail_stated_mixture"]["by_family"])
    rows = [[r["rank"], _a(r["alloc"])] + [_f(r["detail_stated_mixture"]["by_family"].get(f, float("nan")), 2) for f in fams]
            for r in G["ranked"][:k]]
    return _table(["#", "allocation"] + fams, rows)


def _sens_table(G, k=10):
    rows = [[r["rank"], _a(r["alloc"]), _f(r["sens_p10"]), _f(r["sens_p90"]), f"{r['sens_win_freq']:.0%}",
             _f(r["sens_mean_rank"] + 1, 1)] for r in G["ranked"][:k]]
    return _table(["#", "allocation", "p10 score", "p90 score", "ranked #1 in", "mean rank"], rows)


def _stability(G):
    rows = [[s["seed"], " ".join(map(str, s["rank_order"]))] for s in G["seed_stability"]]
    return _table(["population seed", "main-run finalists ordered by score under this seed (main-run rank numbers)"], rows)


def _self_play(G):
    rows = []
    for k, d in G["self_play"].items():
        rows.append([k, len(d["best_responses"]), d["distinct"], d["revisits"], d["distinct_in_second_half"],
                     d["verdict"], _a(d["best_responses"][-1])])
    return _table(["run", "iterations", "distinct BRs", "revisits", "distinct in 2nd half", "verdict", "last BR"], rows)


def _g1_section(G):
    L = ["## Game 1: head-to-head", ""]
    L += ["### Baseline tournament (25 representative allocations, exact round robin)", ""]
    rows = sorted(G["baseline_round_robin"]["rows"], key=lambda r: -r["mean"])
    L += [_table(["allocation", "name", "mean pts", "win", "tie", "loss"],
                 [[_a(r["alloc"]), r["name"], _f(r["mean"]), _f(r["win"], 2), _f(r["tie"], 2), _f(r["loss"], 2)]
                  for r in rows]), ""]
    L += ["![](figures/g1_baseline_round_robin.png)", ""]
    L += ["### Exact best response per scenario (training population) and optimizer benchmark", "",
          "Game 1 scores are additive across castles, so the best response to a finite population is "
          "solved **exactly** (knapsack DP, confirmed by enumerating all 4,598,126 allocations). "
          "The heuristic optimizers are benchmarked against that exact optimum.", ""]
    rows = []
    for n, d in G["per_scenario"].items():
        gaps = {m: max(x["gap"] for x in v) for m, v in d["methods"].items()}
        rows.append([n, _a(d["dp_best"]), _f(d["dp_value"]), _f(d["dp_holdout"]), d["near_optimal_count_0.05"],
                     d["near_optimal_l1_spread"], _f(gaps["random"], 4), _f(gaps["evolutionary"], 4), _f(gaps["local"], 4)])
    L += [_table(["scenario", "exact optimum", "train pts", "holdout pts", "# allocs within 0.05",
                  "max L1 spread", "worst gap random", "worst gap evo", "worst gap local"], rows), ""]
    L += ["![](figures/g1_convergence.png)", "", "![](figures/population_profiles.png)", ""]
    L += ["### A. Top 10 Game 1 allocations (holdout populations, all 7 scenarios)", "",
          "Ranking criterion (fixed before looking at holdout results): **balanced = ½·(equal-weight mean over "
          "scenarios) + ½·(worst scenario)**. Scores are exact expected castle points against each finite "
          "holdout population (no Monte Carlo error); the uncertainty is about which population is real.", ""]
    L += [_ranked_table(G, "g1"), "", _sw_table(G), ""]
    L += ["Per-castle win/tie rates against the pooled stated mixture:", "", _castle_table(G), ""]
    L += ["Mean points by opponent family (pooled stated mixture):", "", _family_table(G), ""]
    L += ["![](figures/g1_top_allocations.png)", "", "![](figures/g1_heatmap.png)", ""]
    L += ["### Robustness", "",
          f"Exact optimum of each criterion over **all** allocations on the holdout populations: "
          + "; ".join(f"{k}: {_a(v[0])}" for k, v in G["exhaustive_holdout_picks"].items()), "",
          "Sensitivity to scenario weights (2,000 Dirichlet(1) weightings; exact because Game 1 is linear in the mixture):", "",
          _sens_table(G), "", "![](figures/g1_sensitivity.png)", "", "![](figures/g1_frontier.png)", "",
          "Exploitability: every pure allocation can be crushed by a counter tailored to it. "
          + "; ".join(f"{_a(r['alloc'])} is held to {_f(r['score_vs_counter'], 1)} by {_a(r['counter_strategy'])}"
                      for r in G["ranked"][:3]) + ". The adversarial scenario measures the realistic version "
          "(a minority of counter-strategies mixed into a population).", "",
          "Seed stability (populations and strategy pools re-drawn from scratch):", "", _stability(G), "",
          "![](figures/g1_seed_stability.png)", ""]
    L += ["### Self-play", "", _self_play(G), "", "![](figures/g1_self_play.png)", ""]
    return L


def _g2_section(G):
    L = ["## Game 2: four-way battle", ""]
    rows = sorted(G["baseline_round_robin"]["rows"], key=lambda r: -r["mean"])
    L += ["### Baseline tournament (exact: each baseline vs every triple of the other 24)", "",
          _table(["allocation", "name", "mean payout", "P(1st/2nd/3rd/4th)", "castle pts"],
                 [[_a(r["alloc"]), r["name"], _f(r["mean"]), " / ".join(f"{p:.2f}" for p in r["pos"]),
                   _f(r["castle_points"], 2)] for r in rows]), ""]
    rows = [[n, _a(d["best"]), _f(d["train_score"]), f"{_f(d['holdout_score'])} ± {_f(1.96 * d['holdout_se'])}"]
            for n, d in G["per_scenario"].items()]
    L += ["### Best response per scenario", "",
          "Optimized on a fixed training field (common random numbers), then re-scored on fresh groups from the "
          "independent holdout population (95% CI shown).", "",
          _table(["scenario", "best found", "train payout", "holdout payout (95% CI)"], rows), "",
          "![](figures/g2_convergence.png)", ""]
    L += ["### B. Top 10 Game 2 allocations (holdout populations, all 7 scenarios)", "",
          f"Validated with {G['validation_groups_final']:,} fresh four-player groups per scenario "
          f"({G['n_candidates_screened']} candidates screened first). Same balanced criterion as Game 1. "
          "Placement probabilities are against the pooled stated mixture.", "",
          _ranked_table(G, "g2"), "", _sw_table(G), ""]
    rows = []
    for r in G["ranked"][:10]:
        p = r["paired_vs_top"]
        rows.append([r["rank"], _a(r["alloc"]), f"{p['mean_diff']:+.4f}", f"[{p['ci95'][0]:+.4f}, {p['ci95'][1]:+.4f}]",
                     p["verdict"]])
    L += ["Paired (common-random-number) comparison vs #1 on the equal-weight scenario mean:", "",
          _table(["#", "allocation", "diff vs #1", "95% CI", "verdict"], rows), "",
          "These intervals capture **Monte Carlo** error only. They do not capture uncertainty about the "
          "population itself; the seed-stability table below is the better guide to that.", ""]
    L += ["Per-castle outright win/tie rates (stated mixture):", "", _castle_table(G), "",
          "Mean payout by opponent family (groups drawn entirely from that family):", "", _family_table(G), "",
          "![](figures/g2_top_allocations.png)", "", "![](figures/g2_placement.png)", "",
          "![](figures/g2_heatmap.png)", ""]
    L += ["### Robustness", "",
          f"Sensitivity: {len(G['ranked'])} finalists re-simulated under random Dirichlet(1) scenario weightings "
          "(mixed populations re-sampled each draw):", "", _sens_table(G), "", "![](figures/g2_sensitivity.png)", "",
          "![](figures/g2_frontier.png)", "", "Targeted exploitation (an optimizer attacks a field where the finalist "
          "is one third of players; the finalist is then scored in a field where that attacker is one third):", "",
          _table(["finalist", "attacker found", "finalist payout vs attacker-heavy field"],
                 [[_a(e["alloc"]), _a(e["attacker"]), f"{_f(e['payout_vs_attacker_heavy_field'])} ± {_f(1.96 * e['se'])}"]
                  for e in G["exploitability"]]), "",
          "Seed stability (populations re-drawn; computed pools reused):", "", _stability(G), "",
          "![](figures/g2_seed_stability.png)", ""]
    L += ["### Self-play", "", _self_play(G), "", "![](figures/g2_self_play.png)", ""]
    return L


def _analysis_section(R):
    A1 = R["g1"]["analysis"]
    L = ["## Strategic analysis", ""]
    rows = []
    for n, d in A1["castle1_sacrifice"].items():
        rows.append([n, f"{_a(d['best_c1_zero'][0])} {_f(d['best_c1_zero'][1])}",
                     f"{_a(d['best_c1_positive'][0])} {_f(d['best_c1_positive'][1])}"])
    L += ["### Castle 1: sacrifice or contest? (Game 1, exact constrained optima, holdout)", "",
          _table(["scenario", "best with C1 = 0", "best with C1 > 0"], rows), ""]
    rows = []
    for n, d in A1["n_targets"].items():
        rows.append([n] + [f"{_a(v[0])} {_f(v[1], 2)}" if v[0] else "-" for v in d.values()])
    L += ["### Number of castles contested (Game 1, exact best with exactly k nonzero castles)", "",
          _table(["scenario"] + [f"k={k}" for k in range(1, 6)], rows), ""]
    rows = []
    for n, d in A1["castle_prices"].items():
        rows.append([n, " / ".join(f"{x:.0f}" for x in d["mean_soldiers"]),
                     " / ".join(f"{x:.0f}" for x in d["soldiers_to_beat_80pct"]),
                     " / ".join(f"{x:.3f}" for x in d["points_per_soldier_80pct"])])
    L += ["### Castle prices: how contested is each castle? (C1/…/C5)", "",
          _table(["scenario", "mean opponent soldiers", "soldiers to beat 80% of opponents",
                  "points per soldier at 80% win rate"], rows), ""]
    rows = [[n, d["count_within_0.05"], d["count_within_0.10"], d["max_l1_from_best"]]
            for n, d in A1["near_optimal"].items()]
    L += ["### Are there many near-equivalent allocations? (Game 1)", "",
          _table(["scenario", "# within 0.05 pts of optimum", "# within 0.10", "max L1 distance among the 0.05 set"], rows), ""]
    rows = [[n, d["alloc"], _f(d["victim_score"], 1)] for n, d in A1["proportional_predictability"].items()]
    L += ["### Predictability (Game 1): score of each allocation against its own tailored counter", "",
          _table(["allocation", "vector", "score vs tailored counter"], rows), ""]
    rows = [[n, _f(d["pick_score"]), _f(d["pick_score_smoothed_pop"]), _f(d["optimum"]), _f(d["optimum_smoothed_pop"]),
             f"{d['share_on_multiples_of_5']:.0%}"] for n, d in A1["artifact_check"].items()]
    L += ["### Does the Game 1 pick exploit artifacts of the simulated populations?", "",
          "Each population is smoothed by moving a few random soldiers per opponent (destroying spikes at round "
          "numbers); a large drop would mean the pick relies on exact tie patterns.", "",
          _table(["scenario", "pick", "pick (smoothed pop)", "optimum", "optimum (smoothed)", "opp. entries on multiples of 5"], rows), ""]
    if "g2" in R:
        A2 = R["g2"]["analysis"]
        L += ["### Game 2 structure", "",
              f"- Correlation between expected castle points and expected payout across {len(R['g2']['ranked'])}+ screened "
              f"candidates: **{A2['corr_points_payout']:.2f}**.",
              f"- Highest castle points: {_a(A2['best_by_points']['alloc'])} ({_f(A2['best_by_points']['points'], 2)} pts, "
              f"payout {_f(A2['best_by_points']['payout'])}). Highest payout: {_a(A2['best_by_payout']['alloc'])} "
              f"({_f(A2['best_by_payout']['points'], 2)} pts, payout {_f(A2['best_by_payout']['payout'])}).",
              f"- Mean allocation of the top-100 screened candidates: {[round(x, 1) for x in A2['top100_mean_alloc']]}; "
              f"number of nonzero castles among them (0–5): {A2['top100_nonzero_castles']}.",
              f"- Best with C1 = 0: {A2['castle1_sacrifice']['best_c1_zero']}; best with C1 > 0: "
              f"{A2['castle1_sacrifice']['best_c1_positive']}.", "",
              "Best screened allocation by number of nonzero castles:", "",
              _table(["k", "best allocation", "payout"], [[k, _a(v[0]) if v[0] else "-", _f(v[1]) if v[0] else "-"]
                                                          for k, v in A2["n_targets"].items()]), "",
              "The Game 1 pick played in Game 2 versus the Game 2 pick (fresh groups):", "",
              _table(["scenario", "G2 pick payout", "G2 pick castle pts", "G1 pick payout", "G1 pick castle pts"],
                     [[n, _f(d["g2_pick"]["payout"]), _f(d["g2_pick"]["points"], 2), _f(d["g1_pick"]["payout"]),
                       _f(d["g1_pick"]["points"], 2)] for n, d in A2["g1_vs_g2_pick"].items()]), "",
              "![](figures/g2_points_vs_payout.png)", ""]
    return L


def _meta_section(R):
    m = R["meta"]
    rows = [[s["stage"], s["seconds"], s["peak_mb"], "yes" if s["completed"] else "NO"] for s in m["stages"]]
    return ["## Run log: what was executed", "",
            f"Mode **{m['mode']}**, finished {m['finished']}, total {m['total_seconds']} s, peak memory "
            f"{m['peak_mb']} MB, Python {m['python']}, NumPy {m['numpy']}, {m['platform']}.", "",
            "Simulation sizes: " + ", ".join(f"{k}={v}" for k, v in m["sim"].items()), "",
            _table(["stage", "seconds", "peak MB (process)", "completed"], rows), ""]


def write_report(R: dict, path: Path):
    path = Path(path)
    L = ["# Castle allocation games: optimization report", "",
         "Automatically generated from `outputs/data/results.json` by `blotto/report.py`. "
         "No scenario below is claimed to be the real applicant population; each is a transparent, configurable "
         "hypothesis used to stress-test the recommendations.", ""]
    narrative = path.parent / "narrative.md"
    if narrative.exists():
        L += [narrative.read_text(), ""]
    L += ["## Scenarios", "", _scenarios(R["g1"]), "",
          f"Each scenario has {R['meta']['sim']['pop_size']:,} training and {R['meta']['sim']['pop_size']:,} independently "
          "seeded holdout opponents. Candidates are selected on training populations and reported on holdout ones. "
          "The adversarial scenario is rebuilt iteratively from best responses to the current finalists.", ""]
    L += _g1_section(R["g1"])
    if "g2" in R:
        L += _g2_section(R["g2"])
    L += _analysis_section(R)
    L += _meta_section(R)
    path.write_text("\n".join(L))
