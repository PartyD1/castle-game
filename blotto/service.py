"""Request-sized operations behind the dashboard API.

Everything here reuses the same engine as the offline pipeline.  Strategy
pools computed offline (outputs/data/pools.json) are loaded for the default
rules; when the user changes castle values, soldiers or payouts the pools are
recomputed at reduced size for that configuration and cached in-process.
"""
from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path

import numpy as np

from .config import DEFAULT_GAME, GameConfig
from .evaluate import g1_round_robin, g2_round_robin, robustness_summary
from .generators import FAMILIES, to_alloc
from .optimize.best_response import g1_best_response_dp, g1_top_k
from .optimize.search import evolutionary, local_search, random_search
from .optimize.self_play import g1_fictitious_play, g2_fictitious_play
from .populations import (SCENARIO_DESCRIPTIONS, SCENARIOS, adversary_pool_g1, adversary_pool_g2, build_pools,
                          sample_population)
from .vectorized import G2Field, as_alloc_array, g1_scores, g1_tables

ROOT = Path(__file__).resolve().parents[1]
POOLS_PATH = ROOT / "outputs" / "data" / "pools.json"

LIMITS = {"pop_size": 20_000, "g2_groups": 200_000, "allocations": 12, "time_budget": 60,
          "soldiers_max": 120, "value_max": 50, "selfplay_iters_g1": 200, "selfplay_iters_g2": 15,
          "tournament_max": 30}


class UserError(ValueError):
    """Bad request input; reported to the user verbatim."""


def make_config(d: dict | None) -> GameConfig:
    d = d or {}
    try:
        cfg = GameConfig(values=tuple(int(v) for v in d.get("values", DEFAULT_GAME.values)),
                         soldiers=int(d.get("soldiers", DEFAULT_GAME.soldiers)),
                         payouts=tuple(float(p) for p in d.get("payouts", DEFAULT_GAME.payouts)))
    except (TypeError, ValueError) as e:
        raise UserError(str(e))
    if cfg.n_castles != 5:
        raise UserError("the dashboard supports exactly 5 castles")
    if not 1 <= cfg.soldiers <= LIMITS["soldiers_max"]:
        raise UserError(f"soldiers must be between 1 and {LIMITS['soldiers_max']}")
    if max(cfg.values) > LIMITS["value_max"]:
        raise UserError(f"castle values must be at most {LIMITS['value_max']}")
    return cfg


def parse_allocs(x, cfg: GameConfig, max_n: int | None = None) -> np.ndarray:
    try:
        A = as_alloc_array(np.asarray(x), cfg)
    except (ValueError, TypeError) as e:
        raise UserError(f"invalid allocation: {e}")
    if max_n and len(A) > max_n:
        raise UserError(f"at most {max_n} allocations per request")
    return A


def _cfg_key(cfg: GameConfig):
    return (cfg.values, cfg.soldiers, cfg.payouts)


@lru_cache(maxsize=1)
def _offline_pools() -> dict:
    if not POOLS_PATH.exists():
        return {}
    raw = json.loads(POOLS_PATH.read_text())
    return {g: {k: np.asarray(v, dtype=np.int64) for k, v in d.items()} for g, d in raw.items()}


@lru_cache(maxsize=8)
def _pools_for(key, game: str) -> dict:
    cfg = GameConfig(values=key[0], soldiers=key[1], payouts=key[2])
    if cfg == DEFAULT_GAME and game in _offline_pools():
        return dict(_offline_pools()[game])
    # strategic pools depend on the castle values (and payouts for G2): recompute, smaller
    rng = np.random.default_rng(7)
    if game == "g1":
        return build_pools("g1", rng, cfg, n_ref=1500, selfplay_iters=20)
    return build_pools("g2", rng, cfg, n_ref=1200, selfplay_iters=9, g2_groups=1500)


def pools(cfg: GameConfig, game: str) -> tuple[dict, bool]:
    """(pools, came_from_offline_run)."""
    key = _cfg_key(cfg)
    offline = cfg == DEFAULT_GAME and game in _offline_pools()
    return _pools_for(key, game), offline


def build_populations(cfg: GameConfig, game: str, pop_size: int, seed: int, custom_weights: dict | None,
                      attack: np.ndarray | None, scenarios: list[str] | None = None) -> tuple[dict, list[str]]:
    """Scenario populations (and an optional custom mixture) for this request."""
    pop_size = int(min(max(pop_size, 100), LIMITS["pop_size"]))
    notes = []
    P, offline = pools(cfg, game)
    P = dict(P)
    if not offline:
        notes.append("Strategic pools were recomputed at reduced size for your custom rules.")
    if attack is not None and len(attack):
        rng = np.random.default_rng(seed + 1)
        P["adversary"] = (adversary_pool_g1(attack, cfg, k=8) if game == "g1"
                          else adversary_pool_g2(attack, rng, cfg, groups=1500))
        notes.append("The adversarial scenario was rebuilt to target your allocations.")
    elif "adversary" not in P:
        notes.append("Adversarial scenario unavailable (no precomputed adversary pool for these rules); "
                     "tick 'attack my allocations' to build one.")
    names = scenarios or list(SCENARIOS)
    out = {}
    for i, n in enumerate(names):
        w = SCENARIOS[n]
        if "adversary" in w and "adversary" not in P:
            continue
        out[n] = sample_population(w, pop_size, np.random.default_rng([seed, i]), P, cfg, n)
    if custom_weights:
        w = {k: float(v) for k, v in custom_weights.items() if float(v) > 0}
        bad = [k for k in w if k not in FAMILIES and k != "adversary"]
        if bad:
            raise UserError(f"unknown families: {bad}")
        if not w:
            raise UserError("custom mixture needs at least one positive weight")
        if "adversary" in w and "adversary" not in P:
            raise UserError("the 'adversary' family needs 'attack my allocations' or default rules")
        out["custom"] = sample_population(w, pop_size, np.random.default_rng([seed, 99]), P, cfg, "custom")
    return out, notes


# --------------------------------------------------------------------------
# operations
# --------------------------------------------------------------------------

def meta() -> dict:
    off = _offline_pools()
    return {"defaults": DEFAULT_GAME.to_dict(), "scenarios": SCENARIOS, "descriptions": SCENARIO_DESCRIPTIONS,
            "families": list(FAMILIES) + ["adversary"], "limits": LIMITS,
            "offline_pools": {g: {k: len(v) for k, v in d.items()} for g, d in off.items()}}


def evaluate(req: dict) -> dict:
    t0 = time.perf_counter()
    cfg = make_config(req.get("config"))
    A = parse_allocs(req.get("allocations"), cfg, LIMITS["allocations"])
    seed = int(req.get("seed", 1))
    pop_size = int(req.get("pop_size", 10_000))
    groups = int(min(max(int(req.get("g2_groups", 50_000)), 1000), LIMITS["g2_groups"]))
    attack = A if req.get("attack_my_allocations") else None
    out = {"allocations": A.tolist(), "notes": []}
    games = req.get("games", ["g1", "g2"])
    for game in games:
        pops, notes = build_populations(cfg, game, pop_size, seed, req.get("custom_weights"), attack)
        out["notes"] += [f"{game.upper()}: {n}" for n in notes]
        names = list(pops)
        if game == "g1":
            S = np.stack([g1_scores(A, g1_tables(p.allocs, cfg)) for p in pops.values()], 1)
            rows = []
            for i, a in enumerate(A):
                stats = {n: {"win": (a[None] > p.allocs).mean(0).tolist(), "tie": (a[None] == p.allocs).mean(0).tolist()}
                         for n, p in pops.items()}
                rows.append({"scores": dict(zip(names, S[i].tolist())), "castle": stats})
            core = [n for n in names if n != "custom"]
            rob = robustness_summary(S[:, [names.index(n) for n in core]], core)
            for i, r in enumerate(rows):
                r.update(mean=float(rob["mean"][i]), worst=float(rob["worst"][i]),
                         worst_scenario=rob["worst_scenario"][i], balanced=float(rob["balanced"][i]))
            out["g1"] = {"scenarios": names, "rows": rows, "max_points": cfg.total_points}
        else:
            rng = np.random.default_rng(seed + 5)
            rows = [{"scores": {}, "se": {}, "pos": {}, "castle_points": {}, "castle_win": {}, "castle_tie": {}}
                    for _ in A]
            for n, p in pops.items():
                ev = G2Field.from_population(p.allocs, rng, groups, cfg).evaluate(A)
                for i in range(len(A)):
                    rows[i]["scores"][n] = float(ev["mean"][i])
                    rows[i]["se"][n] = float(ev["se"][i])
                    rows[i]["pos"][n] = ev["pos"][i].tolist()
                    rows[i]["castle_points"][n] = float(ev["castle_points"][i])
                    rows[i]["castle_win"][n] = ev["castle_win"][i].tolist()
                    rows[i]["castle_tie"][n] = ev["castle_tie"][i].tolist()
            core = [n for n in names if n != "custom"]
            S = np.array([[r["scores"][n] for n in core] for r in rows])
            rob = robustness_summary(S, core)
            for i, r in enumerate(rows):
                r.update(mean=float(rob["mean"][i]), worst=float(rob["worst"][i]),
                         worst_scenario=rob["worst_scenario"][i], balanced=float(rob["balanced"][i]))
            out["g2"] = {"scenarios": names, "rows": rows, "groups": groups, "max_payout": max(cfg.payouts)}
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out


def _objective_pops(req, cfg, game):
    seed = int(req.get("seed", 1))
    target = req.get("target", "broad_mixture")
    custom = req.get("custom_weights") if target == "custom" else None
    scen = None if target in ("balanced", "custom") else [target]
    if target not in ("balanced", "custom") and target not in SCENARIOS:
        raise UserError(f"unknown target {target!r}")
    pops, notes = build_populations(cfg, game, int(req.get("pop_size", 10_000)), seed, custom, None, scen)
    if target == "custom":
        pops = {"custom": pops["custom"]}
    return target, pops, notes


def best_response_g1(req: dict) -> dict:
    t0 = time.perf_counter()
    cfg = make_config(req.get("config"))
    target, pops, notes = _objective_pops(req, cfg, "g1")
    tables = {n: g1_tables(p.allocs, cfg) for n, p in pops.items()}
    k = int(min(max(int(req.get("k", 10)), 1), 50))
    if target == "balanced":
        from .vectorized import all_allocations
        A = all_allocations(cfg)
        S = np.stack([g1_scores(A, t).astype(np.float32) for t in tables.values()], 1)
        v = 0.5 * S.mean(1) + 0.5 * S.min(1)
        idx = np.argpartition(-v, k)[:k]
        idx = idx[np.argsort(-v[idx])]
        top, scores = A[idx].astype(np.int64), v[idx].astype(float)
        method = "exhaustive enumeration of every allocation (balanced = ½ mean + ½ worst over scenarios)"
    else:
        table = next(iter(tables.values()))
        top, scores = g1_top_k(table, k, cfg)
        dp, _ = g1_best_response_dp(table)
        method = f"exact knapsack DP (best {dp.tolist()}) confirmed by exhaustive top-{k}"
    per = {n: g1_scores(top, t).tolist() for n, t in tables.items()}
    return {"target": target, "method": method, "top": top.tolist(), "scores": scores.tolist(), "per_scenario": per,
            "notes": notes, "seconds": round(time.perf_counter() - t0, 2)}


def optimize_g2(req: dict) -> dict:
    t0 = time.perf_counter()
    cfg = make_config(req.get("config"))
    budget = float(min(max(float(req.get("time_budget", 20)), 3), LIMITS["time_budget"]))
    groups = int(min(max(int(req.get("groups", 5000)), 1000), 50_000))
    target, pops, notes = _objective_pops(req, cfg, "g2")
    rng = np.random.default_rng(int(req.get("seed", 1)))
    fields = {n: G2Field.from_population(p.allocs, rng, groups, cfg) for n, p in pops.items()}

    def obj(X):
        S = np.stack([f.mean_payout(X) for f in fields.values()], 1)
        return 0.5 * S.mean(1) + 0.5 * S.min(1) if len(fields) > 1 else S[:, 0]

    deadline = t0 + budget * 0.8
    rs = random_search(obj, rng, 1000, cfg, k=30)
    ev = evolutionary(obj, rng, cfg, pop=80, generations=500, init=rs.top[:20], deadline=deadline, patience=25)
    ls = local_search(obj, ev.top[:2], cfg, steps=(1, 2, 5), deadline=t0 + budget * 0.95)
    top = np.unique(np.concatenate([ev.top[:10], ls.top[:10]]), axis=0)
    # validate on fresh groups so the reported score is not the optimizer's own (optimistic) estimate
    vrng = np.random.default_rng(int(req.get("seed", 1)) + 1000)
    val = {n: G2Field.from_population(p.allocs, vrng, max(4 * groups, 20_000), cfg).evaluate(top) for n, p in pops.items()}
    V = np.stack([v["mean"] for v in val.values()], 1)
    score = 0.5 * V.mean(1) + 0.5 * V.min(1) if V.shape[1] > 1 else V[:, 0]
    order = np.argsort(-score)[:10]
    names = list(val)
    res = [{"alloc": top[i].tolist(), "validated": float(score[i]),
            "per_scenario": {n: float(val[n]["mean"][i]) for n in names},
            "se": {n: float(val[n]["se"][i]) for n in names},
            "pos": {n: val[n]["pos"][i].tolist() for n in names}} for i in order]
    hist = [[int(e), float(s)] for e, s in rs.history + [(e + rs.evaluations, s) for e, s in ev.history]
            + [(e + rs.evaluations + ev.evaluations, s) for e, s in ls.history]]
    return {"target": target, "objective": "balanced over scenarios" if len(fields) > 1 else f"payout vs {target}",
            "results": res, "history": hist, "groups_train": groups, "notes": notes,
            "evaluations": rs.evaluations + ev.evaluations + ls.evaluations,
            "seconds": round(time.perf_counter() - t0, 2)}


def self_play(req: dict) -> dict:
    t0 = time.perf_counter()
    cfg = make_config(req.get("config"))
    game = req.get("game", "g1")
    anchor = float(min(max(float(req.get("anchor", 0.5)), 0.0), 0.95))
    target, pops, notes = _objective_pops({**req, "target": req.get("target", "broad_mixture")}, cfg, game)
    init = np.concatenate([p.allocs for p in pops.values()])
    if game == "g1":
        iters = int(min(max(int(req.get("iters", 60)), 2), LIMITS["selfplay_iters_g1"]))
        res = g1_fictitious_play(init, iters, anchor, cfg)
    elif game == "g2":
        iters = int(min(max(int(req.get("iters", 6)), 2), LIMITS["selfplay_iters_g2"]))
        res = g2_fictitious_play(init, np.random.default_rng(int(req.get("seed", 1))), iters, anchor,
                                 field_size=3000, groups=2500, cfg=cfg, pop=60, generations=15, n_local=2)
    else:
        raise UserError("game must be g1 or g2")
    res.update(notes=notes, seconds=round(time.perf_counter() - t0, 2), start=target, anchor=anchor)
    return res


def tournament(req: dict) -> dict:
    cfg = make_config(req.get("config"))
    A = parse_allocs(req.get("allocations"), cfg, LIMITS["tournament_max"])
    names = req.get("names") or [f"#{i + 1}" for i in range(len(A))]
    if len(names) != len(A):
        raise UserError("names and allocations differ in length")
    if len(A) < 2:
        raise UserError("need at least 2 allocations")
    out = {"g1": g1_round_robin(names, A, cfg)}
    if len(A) >= 4:
        out["g2"] = g2_round_robin(names, A, cfg)
    return out


def rescale(alloc, cfg: GameConfig) -> list[int]:
    return to_alloc(np.asarray(alloc, float)[None], cfg.soldiers)[0].tolist()
