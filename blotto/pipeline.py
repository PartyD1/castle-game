"""End-to-end experiment pipeline for both games.

Results are written as JSON/CSV under outputs/data so the report, plots and
dashboard all read the same numbers.  Each stage records wall time and peak
memory.
"""
from __future__ import annotations

import json
import resource
import sys
import time
from pathlib import Path

import numpy as np

from .config import DEFAULT_GAME, GameConfig, SimConfig
from .evaluate import (baseline_array, g1_detail, g1_round_robin, g1_score_matrix, g2_detail,
                       g2_mixture_sensitivity, g2_round_robin, g2_score_matrix, paired_comparison,
                       robustness_summary, weight_sensitivity)
from .optimize.best_response import g1_best_response_dp, g1_near_optimal, g1_top_k
from .optimize.search import evolutionary, local_search, random_search
from .optimize.self_play import g1_fictitious_play, g2_fictitious_play
from .populations import (SCENARIO_DESCRIPTIONS, SCENARIOS, Population, adversary_pool_g1,
                          adversary_pool_g2, build_pools, build_scenarios)
from .vectorized import G2Field, all_allocations, g1_scores, g1_tables


# --------------------------------------------------------------------------
# bookkeeping
# --------------------------------------------------------------------------

class Log:
    def __init__(self):
        self.t0 = time.perf_counter()
        self.stages = []
        self._start = None

    def peak_mb(self) -> float:
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return r / 1e6 if sys.platform == "darwin" else r / 1e3

    def __call__(self, msg):
        print(f"[{time.perf_counter() - self.t0:8.1f}s | {self.peak_mb():7.0f} MB] {msg}", flush=True)

    def stage(self, name):
        log = self

        class _S:
            def __enter__(s):
                s.t = time.perf_counter()
                log(f"start: {name}")

            def __exit__(s, *exc):
                dt = time.perf_counter() - s.t
                log.stages.append({"stage": name, "seconds": round(dt, 2), "peak_mb": round(log.peak_mb(), 1),
                                   "completed": exc[0] is None})
                log(f"done:  {name} ({dt:.1f}s)")
        return _S()


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return jsonable(o.tolist())
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    return o


def _key(x) -> str:
    return "-".join(str(int(v)) for v in x)


def _uniq(*arrays) -> np.ndarray:
    return np.unique(np.concatenate([np.atleast_2d(a).astype(np.int64) for a in arrays if len(a)]), axis=0)


def _hist(res) -> list:
    return [[int(e), float(s)] for e, s in res.history]


def _describe(alloc, row_scores, names, castle_win, by_family, exploit=None, game="g1") -> tuple[str, str]:
    """Data-driven strengths/vulnerabilities text for one allocation."""
    order = np.argsort(-row_scores)
    strengths = [f"best in '{names[order[0]]}' ({row_scores[order[0]]:.3f})"]
    cw = np.asarray(castle_win)
    strong_c = [f"C{c + 1} {cw[c]:.0%}" for c in np.argsort(-cw)[:2]]
    strengths.append("wins " + ", ".join(strong_c) + " of the time")
    vul = [f"weakest in '{names[order[-1]]}' ({row_scores[order[-1]]:.3f})"]
    if by_family:
        f = min(by_family, key=by_family.get)
        vul.append(f"lowest vs family '{f}' ({by_family[f]:.2f})")
    zero = [f"C{c + 1}" for c in range(len(alloc)) if alloc[c] == 0]
    if zero:
        vul.append("concedes " + ", ".join(zero))
    if exploit is not None:
        vul.append(f"a tailored counter holds it to {exploit:.2f} pts")
    return "; ".join(strengths), "; ".join(vul)


# --------------------------------------------------------------------------
# Game 1
# --------------------------------------------------------------------------

def run_g1(sim: SimConfig, cfg: GameConfig, log: Log) -> dict:
    R: dict = {"scenario_descriptions": SCENARIO_DESCRIPTIONS, "scenario_weights": SCENARIOS}
    rng = np.random.default_rng(sim.master_seed)
    with log.stage("G1 pools"):
        pools = build_pools("g1", rng, cfg, n_ref=4000, selfplay_iters=sim.selfplay_iters)
        R["pool_sizes"] = {k: len(v) for k, v in pools.items()}

    with log.stage("G1 baseline tournament"):
        names_b, B = baseline_array()
        R["baseline_round_robin"] = g1_round_robin(names_b, B, cfg)

    with log.stage("G1 scenarios + per-scenario optimization"):
        train = build_scenarios("g1", pools, sim.pop_size, sim.master_seed, "train", cfg)
        holdout = build_scenarios("g1", pools, sim.pop_size, sim.master_seed, "holdout", cfg)
        per = {}
        cand_parts = [B]
        for name, pop in train.items():
            table = g1_tables(pop.allocs, cfg)
            obj = lambda X, t=table: g1_scores(X, t)
            dp_alloc, dp_val = g1_best_response_dp(table)
            top, top_s = g1_top_k(table, 20, cfg)
            near, _ = g1_near_optimal(table, 0.05, cfg)
            methods = {"random": [], "evolutionary": [], "local": []}
            hist = {}
            for si, seed in enumerate(sim.seeds):
                r = np.random.default_rng(seed)
                rs = random_search(obj, r, sim.n_random_candidates, cfg)
                evs = [evolutionary(obj, r, cfg, pop=sim.evo_pop, generations=sim.evo_generations)
                       for _ in range(sim.evo_restarts)]
                ev = max(evs, key=lambda e: e.best_score)
                ls = local_search(obj, np.concatenate([rs.top[:3], ev.top[:3]]), cfg)
                for m, res in (("random", rs), ("evolutionary", ev), ("local", ls)):
                    methods[m].append({"seed": seed, "best": res.best.tolist(), "score": res.best_score,
                                       "gap": dp_val - res.best_score, "evals": res.evaluations})
                if si == 0:
                    hist = {"random": _hist(rs), "evolutionary": [_hist(e) for e in evs], "local": _hist(ls)}
                cand_parts += [rs.top[:10], ev.top[:10], ls.top[:10]]
            cand_parts.append(top)
            per[name] = {"dp_best": dp_alloc.tolist(), "dp_value": dp_val,
                         "dp_holdout": float(g1_scores(dp_alloc, g1_tables(holdout[name].allocs, cfg))[0]),
                         "top": [{"alloc": a.tolist(), "score": float(s)} for a, s in zip(top, top_s)],
                         "near_optimal_count_0.05": int(len(near)),
                         "near_optimal_l1_spread": int(np.abs(near - near[0]).sum(1).max()) if len(near) else 0,
                         "methods": methods, "history": hist,
                         "pop_mean_alloc": pop.allocs.mean(0).tolist(),
                         "pop_quantiles": np.percentile(pop.allocs, [25, 50, 75, 90], axis=0).tolist()}
            log(f"  G1 {name}: DP {dp_alloc.tolist()} = {dp_val:.4f}")
        R["per_scenario"] = per

    A = all_allocations(cfg)

    def exhaustive_robust(pops, k=60):
        S = np.stack([g1_scores(A, g1_tables(p.allocs, cfg)).astype(np.float32) for p in pops.values()], 1)
        mean, worst = S.mean(1), S.min(1)
        out = {}
        for nm, v in (("mean", mean), ("maximin", worst), ("balanced", 0.5 * mean + 0.5 * worst)):
            idx = np.argpartition(-v, k)[:k]
            idx = idx[np.argsort(-v[idx])]
            out[nm] = A[idx].astype(np.int64)
        del S
        return out

    with log.stage("G1 exhaustive robust search + iterative adversarial scenario"):
        ex = exhaustive_robust(train)
        finalists = ex["balanced"][: sim.n_finalists]
        adv_rounds = []
        adv_pool = adversary_pool_g1(finalists, cfg)
        for rnd in range(2):
            pools["adversary"] = adv_pool
            train = build_scenarios("g1", pools, sim.pop_size, sim.master_seed, "train", cfg)
            ex = exhaustive_robust(train)
            finalists = ex["balanced"][: sim.n_finalists]
            adv_rounds.append({"round": rnd + 1, "pool_size": len(adv_pool), "top_balanced": finalists[:5].tolist()})
            adv_pool = _uniq(adv_pool, adversary_pool_g1(finalists, cfg))
        holdout = build_scenarios("g1", pools, sim.pop_size, sim.master_seed, "holdout", cfg)
        R["adversarial_rounds"] = adv_rounds
        cand_parts += [ex["mean"], ex["maximin"], ex["balanced"]]
        R["exhaustive_train_picks"] = {k: v[:10].tolist() for k, v in ex.items()}

    with log.stage("G1 holdout validation + robustness"):
        C = _uniq(*cand_parts)
        names = list(holdout)
        Sh = g1_score_matrix(C, holdout, cfg)
        St = g1_score_matrix(C, train, cfg)
        rob = robustness_summary(Sh, names)
        order = np.argsort(-rob["balanced"], kind="stable")
        C, Sh, St = C[order], Sh[order], St[order]
        rob = {k: (np.asarray(v)[order] if not isinstance(v, list) else [v[i] for i in order]) for k, v in rob.items()}
        top_n = min(sim.n_finalists, len(C))
        sens = weight_sensitivity(Sh[:top_n], np.random.default_rng(sim.master_seed + 1), 2000)
        mix_pop = Population(np.concatenate([p.allocs for p in holdout.values()]),
                             np.concatenate([p.labels for p in holdout.values()]), "stated_mixture")
        ranked = []
        for i in range(top_n):
            det = g1_detail(C[i], mix_pop, cfg)
            br_alloc, br_val = g1_best_response_dp(g1_tables(C[i][None], cfg))
            exploit = cfg.total_points - br_val
            s_txt, v_txt = _describe(C[i], Sh[i], names, det["castle_win"], det["by_family"], exploit)
            ranked.append({"rank": i + 1, "alloc": C[i].tolist(), "total": int(C[i].sum()),
                           "scenario_scores": dict(zip(names, Sh[i].tolist())),
                           "train_scores": dict(zip(names, St[i].tolist())),
                           "mean": float(rob["mean"][i]), "worst": float(rob["worst"][i]),
                           "worst_scenario": rob["worst_scenario"][i], "balanced": float(rob["balanced"][i]),
                           "cvar_2": float(rob["cvar_2"][i]), "detail_stated_mixture": det,
                           "counter_strategy": br_alloc.tolist(), "score_vs_counter": exploit,
                           "sens_win_freq": float(sens["win_freq"][i]), "sens_mean_rank": float(sens["mean_rank"][i]),
                           "sens_p10": float(sens["p10"][i]), "sens_p90": float(sens["p90"][i]),
                           "strengths": s_txt, "vulnerabilities": v_txt})
        R["ranked"] = ranked
        R["scenario_names"] = names
        R["n_candidates_validated"] = len(C)
        R["pick_by_criterion"] = {
            "mean": C[int(np.argmax(rob["mean"]))].tolist(),
            "maximin": C[int(np.argmax(rob["worst"]))].tolist(),
            "balanced": C[0].tolist(),
        }
        # exact optimum of each criterion over ALL allocations on the holdout populations
        exh = exhaustive_robust(holdout, k=10)
        R["exhaustive_holdout_picks"] = {k: v.tolist() for k, v in exh.items()}
        # baseline performance across scenarios
        Sb = g1_score_matrix(B, holdout, cfg)
        R["baselines_vs_scenarios"] = [{"name": n, "alloc": B[i].tolist(), "scores": dict(zip(names, Sb[i].tolist())),
                                        "by_family": g1_detail(B[i], mix_pop, cfg)["by_family"]}
                                       for i, n in enumerate(names_b)]

    with log.stage("G1 seed stability"):
        top10 = C[:10]
        stab = []
        for seed in sim.seeds:
            p = build_pools("g1", np.random.default_rng(seed), cfg, n_ref=4000, selfplay_iters=sim.selfplay_iters)
            p["adversary"] = pools["adversary"]
            pops = build_scenarios("g1", p, sim.pop_size, seed, "holdout", cfg)
            S = g1_score_matrix(top10, pops, cfg)
            r = robustness_summary(S, list(pops))
            exs = exhaustive_robust(pops, k=1)
            stab.append({"seed": seed, "balanced": r["balanced"].tolist(),
                         "rank_order": (np.argsort(-r["balanced"]) + 1).tolist(),
                         "exhaustive_balanced_best": exs["balanced"][0].tolist()})
        R["seed_stability"] = stab

    with log.stage("G1 self-play"):
        broad = holdout["broad_mixture"].allocs
        R["self_play"] = {f"anchor_{a}": g1_fictitious_play(broad, iters=max(20, sim.selfplay_iters * 2), anchor=a, cfg=cfg)
                          for a in (0.0, 0.5)}

    R["_C"], R["_holdout"], R["_train"], R["_pools"] = C, holdout, train, pools
    return R


# --------------------------------------------------------------------------
# Game 2
# --------------------------------------------------------------------------

def _g2_fields(pops: dict, rng, groups, cfg):
    return {n: G2Field.from_population(p.allocs, rng, groups, cfg) for n, p in pops.items()}


def _balanced_objective(fields: dict):
    def obj(X):
        S = np.stack([f.mean_payout(X) for f in fields.values()], 1)
        return 0.5 * S.mean(1) + 0.5 * S.min(1)
    return obj


def g2_paired_vs_top(X: np.ndarray, fields: dict) -> list[dict]:
    """Paired CRN comparison of each finalist against X[0], per scenario and for the scenario mean."""
    per = {n: paired_comparison(f, X) for n, f in fields.items()}
    out = []
    k = len(fields)
    for i in range(len(X)):
        diffs = np.array([per[n][i]["diff"] for n in fields])
        ses = np.array([per[n][i]["se"] for n in fields])
        m, se = diffs.mean(), np.sqrt((ses ** 2).sum()) / k
        lo, hi = m - 1.96 * se, m + 1.96 * se
        verdict = "reference" if i == 0 else ("worse" if hi < 0 else "better" if lo > 0 else "inconclusive")
        out.append({"mean_diff": float(m), "se": float(se), "ci95": [float(lo), float(hi)], "verdict": verdict,
                    "per_scenario": {n: per[n][i] for n in fields}})
    return out


def run_g2(sim: SimConfig, cfg: GameConfig, log: Log, g1_finalists: np.ndarray | None = None) -> dict:
    from .optimize.best_response import g2_best_response
    from .optimize.search import random_candidates

    R: dict = {"scenario_descriptions": SCENARIO_DESCRIPTIONS, "scenario_weights": SCENARIOS}
    rng = np.random.default_rng(sim.master_seed + 100)
    restarts = max(1, sim.evo_restarts // 2)
    with log.stage("G2 pools"):
        pools = build_pools("g2", rng, cfg, n_ref=3000, selfplay_iters=sim.selfplay_iters,
                            g2_groups=min(4000, sim.g2_screen_groups))
        R["pool_sizes"] = {k: len(v) for k, v in pools.items()}

    with log.stage("G2 baseline tournament"):
        names_b, B = baseline_array()
        R["baseline_round_robin"] = g2_round_robin(names_b, B, cfg)

    with log.stage("G2 scenarios + per-scenario optimization"):
        train = build_scenarios("g2", pools, sim.pop_size, sim.master_seed, "train", cfg)
        holdout = build_scenarios("g2", pools, sim.pop_size, sim.master_seed, "holdout", cfg)
        per, cand_parts = {}, [B]
        seed_init = g1_finalists[:20] if g1_finalists is not None else None
        if seed_init is not None:
            cand_parts.append(seed_init)
        for name, pop in train.items():
            r = np.random.default_rng(sim.seeds[0])
            field = G2Field.from_population(pop.allocs, r, sim.g2_screen_groups, cfg)
            obj = field.mean_payout
            rs = random_search(obj, r, sim.n_random_candidates, cfg)
            evs = [evolutionary(obj, r, cfg, pop=sim.evo_pop, generations=sim.evo_generations, init=seed_init)
                   for _ in range(restarts)]
            ev = max(evs, key=lambda e: e.best_score)
            ls = local_search(obj, np.concatenate([rs.top[:2], ev.top[:3]]), cfg)
            best = max((rs, ev, ls), key=lambda x: x.best_score)
            hfield = G2Field.from_population(holdout[name].allocs, r, sim.g2_validate_groups // 4, cfg)
            hev = hfield.evaluate(best.top[:1])
            per[name] = {"best": best.best.tolist(), "train_score": best.best_score,
                         "holdout_score": float(hev["mean"][0]), "holdout_se": float(hev["se"][0]),
                         "methods": {m: {"best": x.best.tolist(), "score": x.best_score, "evals": x.evaluations}
                                     for m, x in (("random", rs), ("evolutionary", ev), ("local", ls))},
                         "history": {"random": _hist(rs), "evolutionary": [_hist(e) for e in evs], "local": _hist(ls)},
                         "top": [{"alloc": a.tolist(), "score": float(s)} for a, s in zip(best.top[:10], best.scores[:10])]}
            cand_parts += [rs.top[:15], ev.top[:15], ls.top[:15]]
            log(f"  G2 {name}: {best.best.tolist()} train {best.best_score:.4f} holdout {hev['mean'][0]:.4f}")
        R["per_scenario"] = per

    with log.stage("G2 screening set for strategic analysis"):
        r = np.random.default_rng(sim.seeds[0] + 7)
        Xs = _uniq(random_candidates(r, sim.n_random_candidates, cfg), *cand_parts)
        bf = G2Field.from_population(train["broad_mixture"].allocs, r, sim.g2_screen_groups, cfg)
        ev = bf.evaluate(Xs)
        R["_screen"] = {"allocs": Xs, "mean": ev["mean"], "castle_points": ev["castle_points"], "pos": ev["pos"]}

    with log.stage("G2 robust optimization + iterative adversarial scenario"):
        r = np.random.default_rng(sim.seeds[0] + 1)
        small = max(2000, sim.g2_screen_groups // 4)
        adv_rounds = []
        for rnd in range(3):
            fields = _g2_fields(train, r, small, cfg)
            obj = _balanced_objective(fields)
            C0 = _uniq(*cand_parts)
            starts = C0[np.argsort(-obj(C0))[:40]]
            ev = evolutionary(obj, r, cfg, pop=sim.evo_pop // 2, generations=sim.evo_generations // 2, init=starts)
            ls = local_search(obj, ev.top[:3], cfg, steps=(1, 2, 5))
            cand_parts += [ev.top[:20], ls.top[:20], starts[:20]]
            C0 = _uniq(*cand_parts)
            finalists = C0[np.argsort(-obj(C0))[: sim.n_finalists]]
            adv_rounds.append({"round": rnd, "scenarios": list(train), "top_balanced": finalists[:5].tolist(),
                               "robust_history": _hist(ev)})
            log(f"  G2 robust round {rnd}: top {finalists[0].tolist()}")
            if rnd == 2:
                break
            new = adversary_pool_g2(finalists, r, cfg, background=train["broad_mixture"].allocs,
                                    groups=min(3000, sim.g2_screen_groups))
            pools["adversary"] = new if "adversary" not in pools else _uniq(pools["adversary"], new)
            train = build_scenarios("g2", pools, sim.pop_size, sim.master_seed, "train", cfg)
        holdout = build_scenarios("g2", pools, sim.pop_size, sim.master_seed, "holdout", cfg)
        R["adversarial_rounds"] = adv_rounds
        R["adversary_pool_size"] = len(pools["adversary"])

    with log.stage("G2 holdout validation (screen all candidates)"):
        r = np.random.default_rng(sim.seeds[0] + 2)
        C = _uniq(*cand_parts)
        names = list(holdout)
        M, _ = g2_score_matrix(C, holdout, r, max(20_000, sim.g2_validate_groups // 4), cfg)
        C = C[np.argsort(-robustness_summary(M, names)["balanced"])]
        R["n_candidates_screened"] = len(C)

    with log.stage("G2 finalist validation (fresh groups, paired CRN)"):
        r = np.random.default_rng(sim.seeds[0] + 3)
        F = C[: sim.n_finalists]
        groups = sim.g2_validate_groups
        fields = _g2_fields(holdout, r, groups, cfg)
        M = np.stack([fields[n].mean_payout(F) for n in names], 1)
        order = np.argsort(-robustness_summary(M, names)["balanced"])
        F, M = F[order], M[order]
        paired = g2_paired_vs_top(F, fields)
        escalations = []
        # escalate sample size while the top-2 comparison remains inconclusive
        while paired[1]["verdict"] == "inconclusive" and groups < 4 * sim.g2_validate_groups:
            groups *= 2
            log(f"  top-2 inconclusive -> re-validating top 10 with {groups} groups per scenario")
            fields = _g2_fields(holdout, r, groups, cfg)
            top = F[:10]
            Mt = np.stack([fields[n].mean_payout(top) for n in names], 1)
            o = np.argsort(-robustness_summary(Mt, names)["balanced"])
            F = np.concatenate([top[o], F[10:]])
            M = np.concatenate([Mt[o], M[10:]])
            paired = g2_paired_vs_top(F[:10], fields) + paired[10:]
            escalations.append({"groups": groups, "verdict_top2": paired[1]["verdict"]})
        R["validation_groups_final"] = groups
        R["escalations"] = escalations
        SEs = np.stack([fields[n].evaluate(F[:10])["se"] for n in names], 1)
        rob = robustness_summary(M, names)
        mix_pop = Population(np.concatenate([p.allocs for p in holdout.values()]),
                             np.concatenate([p.labels for p in holdout.values()]), "stated_mixture")
        det = g2_detail(F, mix_pop, r, groups, cfg, family_groups=20_000)
        sens = g2_mixture_sensitivity(F, holdout, np.random.default_rng(sim.master_seed + 5), sim.sensitivity_draws,
                                      max(5000, sim.g2_screen_groups // 2), sim.pop_size, cfg)
        ranked = []
        for i in range(len(F)):
            s_txt, v_txt = _describe(F[i], M[i], names, det[i]["castle_win"], det[i]["by_family"])
            ranked.append({"rank": i + 1, "alloc": F[i].tolist(), "total": int(F[i].sum()),
                           "scenario_scores": dict(zip(names, M[i].tolist())),
                           "scenario_se": dict(zip(names, SEs[i].tolist())) if i < 10 else None,
                           "mean": float(rob["mean"][i]), "worst": float(rob["worst"][i]),
                           "worst_scenario": rob["worst_scenario"][i], "balanced": float(rob["balanced"][i]),
                           "cvar_2": float(rob["cvar_2"][i]),
                           "paired_vs_top": {k: v for k, v in paired[i].items() if k != "per_scenario"},
                           "detail_stated_mixture": det[i], "sens_win_freq": float(sens["win_freq"][i]),
                           "sens_mean_rank": float(sens["mean_rank"][i]), "sens_p10": float(sens["p10"][i]),
                           "sens_p90": float(sens["p90"][i]), "strengths": s_txt, "vulnerabilities": v_txt})
        R["ranked"] = ranked
        R["scenario_names"] = names
        R["pick_by_criterion"] = {"mean": F[int(np.argmax(rob["mean"]))].tolist(),
                                  "maximin": F[int(np.argmax(rob["worst"]))].tolist(),
                                  "balanced": F[0].tolist()}
        Mb, _ = g2_score_matrix(B, holdout, r, max(20_000, sim.g2_validate_groups // 4), cfg)
        R["baselines_vs_scenarios"] = [{"name": n, "alloc": B[i].tolist(), "scores": dict(zip(names, Mb[i].tolist()))}
                                       for i, n in enumerate(names_b)]

    with log.stage("G2 targeted exploitability of top finalists"):
        r = np.random.default_rng(sim.seeds[0] + 4)
        bg = holdout["broad_mixture"].allocs
        expl = []
        for i in range(min(5, len(F))):
            # attack a field where this finalist is common (1/3 of players) ...
            field_pop = np.concatenate([np.repeat(F[i][None], 1000, 0), bg[r.integers(0, len(bg), 2000)]])
            atk = g2_best_response(field_pop, r, cfg, groups=min(4000, sim.g2_screen_groups), generations=20)
            # ... then score the finalist in a field where that attacker is common
            atk_pop = np.concatenate([np.repeat(atk.best[None], 1000, 0), bg[r.integers(0, len(bg), 2000)]])
            fv = G2Field.from_population(atk_pop, r, 50_000, cfg).evaluate(F[i][None])
            expl.append({"alloc": F[i].tolist(), "attacker": atk.best.tolist(),
                         "payout_vs_attacker_heavy_field": float(fv["mean"][0]), "se": float(fv["se"][0])})
        R["exploitability"] = expl

    with log.stage("G2 seed stability"):
        top10 = F[:10]
        stab = []
        for seed in sim.seeds:
            pops = build_scenarios("g2", pools, sim.pop_size, seed, "holdout", cfg)
            Ms, _ = g2_score_matrix(top10, pops, np.random.default_rng(seed), max(20_000, sim.g2_validate_groups // 4), cfg)
            rr = robustness_summary(Ms, list(pops))
            stab.append({"seed": seed, "balanced": rr["balanced"].tolist(),
                         "rank_order": (np.argsort(-rr["balanced"]) + 1).tolist()})
        R["seed_stability"] = stab

    with log.stage("G2 self-play"):
        broad = holdout["broad_mixture"].allocs
        iters = max(6, sim.selfplay_iters // 3)
        R["self_play"] = {f"anchor_{a}": g2_fictitious_play(broad, np.random.default_rng(sim.seeds[0] + 9), iters=iters,
                                                            anchor=a, groups=min(4000, sim.g2_screen_groups), cfg=cfg)
                          for a in (0.0, 0.5)}

    R["_F"], R["_holdout"], R["_train"], R["_pools"] = F, holdout, train, pools
    return R
