# Castle allocation lab

Optimization system for two Colonel Blotto-style games (100 soldiers, castles worth 1–5):

- **Game 1 (head-to-head):** maximize average castle points against every other applicant.
- **Game 2 (four-way):** maximize average placement payout (9 / 4 / 2 / 0) in random groups of four.

The applicant population is unknown, so allocations are optimized and stress-tested against seven
transparent, hypothetical populations rather than a guessed "real" one.

**Results:** [`outputs/REPORT.md`](outputs/REPORT.md) (recommendations, top-10 tables, robustness, statistics,
figures, and the application response). Raw numbers are in `outputs/data/` (`results.json`, `g1_ranked.csv`,
`g2_ranked.csv`).

## Layout

| path | what |
|---|---|
| `blotto/scoring.py` | exact scalar reference: `validate_allocation`, `score_head_to_head`, `score_four_way`, `calculate_rank_payouts` |
| `blotto/vectorized.py` | batch engines: Game 1 per-castle lookup tables (exact), Game 2 CRN field evaluator |
| `blotto/generators.py` | 12 opponent strategy families |
| `blotto/populations.py` | 7 scenario mixtures, computed strategy pools, train/holdout splits |
| `blotto/optimize/` | exact G1 best response (knapsack DP + exhaustive enumeration), random / evolutionary / local search, G2 best response, fictitious-play self-play |
| `blotto/evaluate.py` | tournaments, paired CRN comparisons, robustness and sensitivity |
| `blotto/pipeline.py`, `scripts/run_all.py` | the full experiment pipeline |
| `blotto/analysis.py`, `blotto/plots.py`, `blotto/report.py` | strategic analysis, figures, report |
| `app.py`, `blotto/service.py`, `public/index.html` | interactive dashboard (FastAPI + static page), deployable on Vercel |

## Run it

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q                 # unit tests
.venv/bin/python scripts/run_all.py --quick   # ~2 min smoke run (writes to outputs/)
.venv/bin/python scripts/run_all.py           # full run (~10–20 min on a laptop)
.venv/bin/uvicorn app:app --port 8000         # dashboard at http://localhost:8000
```

`--quick` and full runs both write to `outputs/` by default; pass `--out DIR` to write elsewhere.

## Dashboard

The dashboard lets you change castle values, soldier count, payouts and opponent mixtures. You can then
evaluate your own allocations in both games, find exact Game 1 best responses, run the Game 2 optimizer,
run self-play, and hold round-robin tournaments among your own list.

With the official rules, seed 2026 and 10,000 opponents per scenario, it rebuilds the holdout populations used
in the report: exactly when run locally on the machine that produced the report. On Vercel (x86 Linux),
last-bit floating-point differences in `exp`/`log` occasionally flip a rounding decision when generating an
opponent. In testing, 6 of 7 Game 1 scenario scores matched to 4 decimals and broad_mixture differed by 0.011
points. Changing the rules recomputes the strategic opponent pools at reduced size.

Deploy: `vercel deploy` (FastAPI is detected from `app.py`; `public/` is served statically).
