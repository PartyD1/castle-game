"""Matplotlib figures built from results.json."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

CASTLES = ["C1 (1)", "C2 (2)", "C3 (3)", "C4 (4)", "C5 (5)"]
plt.rcParams.update({"figure.dpi": 110, "savefig.bbox": "tight", "axes.grid": True, "grid.alpha": 0.3,
                     "font.size": 9})


def _save(fig, path: Path):
    fig.savefig(path)
    plt.close(fig)


def _lbl(a):
    return "[" + ",".join(map(str, a)) + "]"


def convergence(G: dict, game: str, out: Path):
    per = G["per_scenario"]
    names = list(per)
    fig, axes = plt.subplots(2, (len(names) + 1) // 2, figsize=(4 * ((len(names) + 1) // 2), 6.5), squeeze=False, layout="constrained")
    for ax, n in zip(axes.flat, names):
        h = per[n]["history"]
        ref = per[n].get("dp_value")
        for e in h["evolutionary"]:
            x, y = np.array(e).T
            ax.plot(x, (ref - y) if ref else y, color="tab:blue", alpha=0.6, lw=1)
        x, y = np.array(h["random"]).T
        ax.plot(x, (ref - y) if ref else y, color="tab:orange", lw=1.5, marker="o", ms=3, label="random search")
        ax.plot([], [], color="tab:blue", label="evolutionary (restarts)")
        if ref:
            ax.set_yscale("symlog", linthresh=1e-3)
            ax.set_ylabel("gap to exact optimum (pts)")
        else:
            ax.set_ylabel("best payout on CRN field")
        ax.set_title(n)
        ax.set_xlabel("evaluations")
    for ax in list(axes.flat)[len(names):]:
        ax.axis("off")
    axes.flat[0].legend()
    fig.suptitle(f"{game.upper()} optimizer convergence per scenario")
    _save(fig, out / f"{game}_convergence.png")


def population_profiles(G: dict, out: Path):
    per = G["per_scenario"]
    fig, ax = plt.subplots(figsize=(9, 4))
    w = 0.8 / len(per)
    for i, (n, d) in enumerate(per.items()):
        q = np.array(d["pop_quantiles"])  # 25, 50, 75, 90
        x = np.arange(5) + i * w - 0.4 + w / 2
        ax.bar(x, q[1], w, label=n, alpha=0.8)
        ax.errorbar(x, q[1], yerr=[q[1] - q[0], q[2] - q[1]], fmt="none", ecolor="k", lw=0.7)
    ax.set_xticks(range(5), CASTLES)
    ax.set_ylabel("soldiers (median, IQR)")
    ax.set_title("Opponent allocations per castle by scenario (Game 1 training populations)")
    ax.legend(ncol=4, fontsize=7)
    _save(fig, out / "population_profiles.png")


def top_allocations(G: dict, game: str, out: Path, k: int = 10):
    R = G["ranked"][:k]
    X = np.array([r["alloc"] for r in R])
    fig, ax = plt.subplots(figsize=(8, 0.35 * k + 1.2))
    left = np.zeros(len(X))
    colors = plt.cm.viridis(np.linspace(0.1, 0.9, 5))
    for c in range(5):
        ax.barh(range(len(X)), X[:, c], left=left, color=colors[c], label=CASTLES[c])
        for i, v in enumerate(X[:, c]):
            if v >= 4:
                ax.text(left[i] + v / 2, i, str(v), ha="center", va="center", fontsize=7, color="w")
        left += X[:, c]
    ax.set_yticks(range(len(X)), [f"#{r['rank']}" for r in R])
    ax.invert_yaxis()
    ax.set_xlabel("soldiers")
    ax.set_title(f"{game.upper()} top-{k} allocations")
    ax.legend(ncol=5, fontsize=7, loc="lower center", bbox_to_anchor=(0.5, 1.06))
    _save(fig, out / f"{game}_top_allocations.png")


def heatmap(G: dict, game: str, out: Path, k: int = 15):
    R = G["ranked"][:k]
    names = G["scenario_names"]
    M = np.array([[r["scenario_scores"][n] for n in names] for r in R])
    fig, ax = plt.subplots(figsize=(1.1 * len(names) + 3, 0.38 * len(R) + 1.5))
    im = ax.imshow(M, aspect="auto", cmap="viridis")
    ax.set_xticks(range(len(names)), names, rotation=30, ha="right")
    ax.set_yticks(range(len(R)), [f"#{r['rank']} {_lbl(r['alloc'])}" for r in R])
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            ax.text(j, i, f"{M[i, j]:.2f}", ha="center", va="center", fontsize=7,
                    color="w" if M[i, j] < M.mean() else "k")
    fig.colorbar(im, ax=ax, label="expected castle points" if game == "g1" else "expected payout")
    ax.set_title(f"{game.upper()} finalists x scenario (holdout populations)")
    _save(fig, out / f"{game}_heatmap.png")


def baseline_heatmap(G: dict, out: Path):
    rows = G["baseline_round_robin"]["rows"]
    M = np.array(G["baseline_round_robin"]["matrix"])
    order = np.argsort([-r["mean"] for r in rows])
    M = M[np.ix_(order, order)]
    labels = [rows[i]["name"] for i in order]
    fig, ax = plt.subplots(figsize=(9, 8))
    im = ax.imshow(M, cmap="RdBu", vmin=0, vmax=15)
    ax.set_xticks(range(len(labels)), labels, rotation=90, fontsize=7)
    ax.set_yticks(range(len(labels)), labels, fontsize=7)
    fig.colorbar(im, ax=ax, label="row player's castle points")
    ax.set_title("Game 1 baseline round robin (sorted by mean)")
    ax.grid(False)
    _save(fig, out / "g1_baseline_round_robin.png")


def placement(G: dict, out: Path, k: int = 10):
    R = G["ranked"][:k]
    P = np.array([r["detail_stated_mixture"]["pos"] for r in R])
    base = sorted(G["baseline_round_robin"]["rows"], key=lambda r: -r["mean"])[:5]
    PB = np.array([r["pos"] for r in base])
    allP = np.concatenate([P, PB])
    labels = [f"#{r['rank']} {_lbl(r['alloc'])}" for r in R] + [f"baseline {r['name']}*" for r in base]
    fig, ax = plt.subplots(figsize=(8, 0.35 * len(allP) + 1.5))
    left = np.zeros(len(allP))
    cols = ["#2a9d8f", "#8ab17d", "#e9c46a", "#e76f51"]
    for j, nm in enumerate(["1st (9)", "2nd (4)", "3rd (2)", "4th (0)"]):
        ax.barh(range(len(allP)), allP[:, j], left=left, color=cols[j], label=nm)
        left += allP[:, j]
    ax.set_yticks(range(len(allP)), labels, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xlabel("probability (ties split across shared ranks)")
    ax.set_title("Game 2 placement probabilities (finalists vs stated mixture; *baselines in their own round robin)")
    ax.legend(ncol=4, fontsize=7, loc="lower center", bbox_to_anchor=(0.5, 1.04))
    _save(fig, out / "g2_placement.png")


def sensitivity(G: dict, game: str, out: Path, k: int = 15):
    R = G["ranked"][:k]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 0.35 * len(R) + 1.5), sharey=True)
    y = np.arange(len(R))
    lo = np.array([r["sens_p10"] for r in R])
    hi = np.array([r["sens_p90"] for r in R])
    a1.hlines(y, lo, hi, color="tab:blue", lw=3)
    a1.plot([r["mean"] for r in R], y, "k|", ms=10, label="equal-weight mean")
    a1.plot([r["worst"] for r in R], y, "rx", label="worst scenario")
    a1.set_yticks(y, [f"#{r['rank']} {_lbl(r['alloc'])}" for r in R], fontsize=7)
    a1.invert_yaxis()
    a1.set_title("score range under random scenario weights (10th-90th pct)")
    a1.legend(fontsize=7)
    a2.barh(y, [r["sens_win_freq"] for r in R], color="tab:green")
    a2.set_title("share of random weightings where it ranks #1")
    a2.set_xlim(0, 1)
    fig.suptitle(f"{game.upper()} sensitivity to population mixture weights")
    _save(fig, out / f"{game}_sensitivity.png")


def frontier(G: dict, game: str, out: Path):
    R = G["ranked"]
    m = np.array([r["mean"] for r in R])
    w = np.array([r["worst"] for r in R])
    fig, ax = plt.subplots(figsize=(6, 4.5))
    ax.scatter(m, w, c=np.arange(len(R)), cmap="viridis_r", s=25)
    for r in R[:5]:
        ax.annotate(f"#{r['rank']} {_lbl(r['alloc'])}", (r["mean"], r["worst"]), fontsize=7,
                    xytext=(4, 4), textcoords="offset points")
    ax.set_xlabel("mean over scenarios (expected)")
    ax.set_ylabel("worst-case scenario (robust)")
    ax.set_title(f"{game.upper()} finalists: expected vs robust")
    _save(fig, out / f"{game}_frontier.png")


def self_play(G: dict, game: str, out: Path):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.5))
    for k, d in G["self_play"].items():
        a1.plot(d["br_value"], marker=".", label=k)
        a2.plot(d["l1_step"], marker=".", label=k)
    a1.set_title("best-response value vs current field")
    a1.set_xlabel("iteration")
    a2.set_title("L1 change between consecutive best responses")
    a2.set_xlabel("iteration")
    a1.legend(fontsize=7)
    fig.suptitle(f"{game.upper()} self-play (fictitious play)")
    _save(fig, out / f"{game}_self_play.png")


def seed_stability(G: dict, game: str, out: Path):
    fig, ax = plt.subplots(figsize=(7, 3.5))
    R = G["ranked"][:10]
    for s in G["seed_stability"]:
        ax.plot(range(1, len(s["balanced"]) + 1), s["balanced"], marker="o", label=f"seed {s['seed']}")
    ax.plot(range(1, len(R) + 1), [r["balanced"] for r in R], "k--", label="main holdout")
    ax.set_xlabel("finalist rank (main run)")
    ax.set_ylabel("balanced score")
    ax.set_title(f"{game.upper()} finalist scores under independently re-drawn populations")
    ax.legend(fontsize=7)
    _save(fig, out / f"{game}_seed_stability.png")


def g2_points_vs_payout(screen_path: Path, out: Path):
    if not screen_path.exists():
        return
    d = np.load(screen_path)
    fig, ax = plt.subplots(figsize=(6, 4.5))
    ax.scatter(d["castle_points"], d["mean"], s=4, alpha=0.4)
    ax.set_xlabel("expected castle points in a 4-player group")
    ax.set_ylabel("expected placement payout")
    ax.set_title("Game 2: castle points vs payout (screened candidates, broad mixture)")
    _save(fig, out / "g2_points_vs_payout.png")


def make_all(results: dict, out: Path):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    g1 = results["g1"]
    convergence(g1, "g1", out)
    population_profiles(g1, out)
    baseline_heatmap(g1, out)
    for game in ("g1", "g2"):
        if game not in results:
            continue
        G = results[game]
        top_allocations(G, game, out)
        heatmap(G, game, out)
        sensitivity(G, game, out)
        frontier(G, game, out)
        self_play(G, game, out)
        seed_stability(G, game, out)
    if "g2" in results:
        convergence(results["g2"], "g2", out)
        placement(results["g2"], out)
        g2_points_vs_payout(out.parent / "data" / "g2_screen.npz", out)
