## Summary

| | Recommendation | Optimized for | Scenario mean | Worst scenario | Most likely alternative |
|---|---|---|---|---|---|
| **Game 1** | **[2, 3, 5, 37, 53]** | robustness (½·mean + ½·worst case, fixed in advance) | 9.05 castle pts | 8.78 (adversarial) | [1, 1, 22, 35, 41] if you believe most applicants are intuitive |
| **Game 2** | **[0, 0, 39, 61, 0]** | the same balanced criterion; also the best scenario mean among finalists | 7.22 payout | 5.86 (adversarial) | [0, 0, 38, 62, 0] (tied at population level); [0, 0, 28, 0, 72] (different structure) |

Every number in this report comes from code that was executed. Game 1 scores are exact against each simulated
population. Game 2 scores are Monte Carlo estimates on 200,000 fresh four-player groups per scenario, with
standard errors of about 0.004–0.008. None of this proves optimality against the real applicant pool. Each result
is optimal or robust **with respect to the seven modeled populations**, and those populations are hypotheses.

## C. Final comparison

### Game 1: recommend [2, 3, 5, 37, 53]

**Why.** It ranks first on the pre-specified balanced criterion on held-out populations. It also lies on the
**exact** mean-vs-worst-case Pareto frontier, computed over all 4,598,126 allocations (see the supplementary
section). It wins 85% of head-to-head matchups against the pooled mixture of all scenarios. The idea is to concede
castle 3 and scrap for castles 1–2 with a token 2–3 soldiers. Then dominate the two most valuable castles: it wins
castle 5 against 92% of opponents and castle 4 against 77%.

**Expected vs robust.** This is a deliberate robustness choice, and the trade-off is sharp:

- **Expected-score optimum:** [1, 1, 22, 35, 41] has the highest scenario mean (9.18). It scores about 11.0
  against intuitive populations (balanced, proportional), but only 7.3–7.4 against strategic and adversarial ones.
- **Robust pick:** [2, 3, 5, 37, 53] gives up 0.13 points of mean to raise the worst case from 7.34 to 8.78.
  Across all seven scenarios it stays within 8.78–9.20.
- **Cheap robustness:** the frontier is steep near the mean optimum. The first 0.11 points of mean you give up
  buy 1.2 points of worst case.

**Sensitivity.**
- Under 2,000 random reweightings of the seven scenarios, it is the top finalist 60% of the time. The next-best finalist reaches
  18%.
- When the populations and strategy pools are re-drawn from scratch with three other seeds, the exact balanced
  optimum moves to [2, 3, 5, 36, 54] or [2, 2, 6, 36, 54], i.e. by 1–2 soldiers. In all three re-draws,
  main-run #8, [2, 3, 5, 36, 54], ranks first.
- Smoothing every opponent's allocation changes its scores by at most 0.16 points (largest change: strategic),
  so it does not depend on tie spikes at round numbers.

**Statistically indistinguishable alternatives.** The ten finalists are all within 0.025 balanced points of each
other, and their order reshuffles when populations are re-drawn. Treat **[2–3, 2–3, 5–6, 36–37, 53–55]** as one
recommendation. The specific vector is the main run's pick.

**Caveat on the adversarial scenario.** If you drop the adversarial scenario (it is built from counters to our
own finalists), a different robust family appears: [1, 12, 1, 40, 46] reaches a worst case of 9.04 over the other
six scenarios. But it falls to 6.7 in the adversarial scenario, so including it is what favors the recommendation.

### Game 2: recommend [0, 0, 39, 61, 0]

**Why.** Win castles 3 and 4 outright (7 of 15 points) and concede castles 1, 2 and 5 entirely.
- **Why 7 points is usually enough:** an opponent can beat 7 only by winning all of castles 1, 2 and 5 (8 points)
  alone.
- **Placement odds:** it finishes first 70% of the time against the pooled mixture. Its distribution is
  70 / 16 / 11 / 3% for first / second / third / fourth.
- **Ranking:** it ranks first among the 25 validated finalists on the balanced criterion and has the best
  scenario mean (7.22).
- **Tailored attack:** an optimizer built an attacker for a field where this allocation is one-third of the
  players. The best counter found was [1, 30, 0, 0, 69], and the pick still earned 7.15 against it.

**How Game 2 changes the strategy.** The payouts are convex (9 for first versus 4 for second), so coming first
matters much more than collecting points. The Game 1 pick played in Game 2 averages only 2.3 against the strategic
population and 4.8 against the broad mixture. Game 2 rewards concentrating on exactly two castles worth 7.

**Statistical status.**
- **Monte Carlo error is small:** the paired, common-random-number comparisons rank the pick above every other
  finalist on the scenario mean, with 95% intervals excluding zero.
- **Population uncertainty is larger:** that precision does not carry over to the population assumptions.
  - Seed re-draws: [0, 0, 39, 61, 0] and [0, 0, 38, 62, 0] swap first and second place.
  - Smoothed opponents: 38/62 edges ahead on the balanced score (6.54 vs 6.52).
  - So **39/61 and 38/62 are indistinguishable at the population level**, and 39/61 keeps the higher mean in
    every check.
- **The exact split is fragile:** the optimizer is partly reacting to how often simulated players put exactly
  38–40 soldiers on castle 3. The robust conclusion is the structure (castles 3+4, roughly 38–40 / 60–62, nothing
  elsewhere), not the last soldier.

**A genuinely different alternative.** [0, 0, 28, 0, 72] (castles 3+5) has a similar scenario mean (7.15). It
ranks first in 41% of random scenario reweightings, versus 30% for the pick. It does better against strategic and
adversarial populations, but collapses against concentrated players (5.6). Choose it if you expect many
computationally optimized applicants and few who stack castles 4 and 5.

### What did not converge, and what was not done

- **Self-play does not converge in either game.**
  - Game 1: fictitious play visited 55–68 distinct best responses in 80 iterations.
  - Game 2: it visited 13 distinct best responses in 13 iterations.
  - This is consistent with Colonel Blotto having no pure-strategy equilibrium. Strong pure allocations are
    always exploitable by a tailored counter: [2, 3, 5, 37, 53] is held to 2.5 points by [2, 0, 6, 38, 54].
- **Seed coverage:**
  - Game 2's per-scenario optimization ran on one optimizer seed. Robustness across seeds was tested by
    re-drawing populations three times.
  - Game 2's seed-stability check reused the computed strategy pools rather than recomputing them.
  - Game 1's stability check recomputed everything.
- **Scope of the Game 1 optimum:** the "exact optimum" claims for Game 1 hold only for the finite simulated
  populations.

## D. Application response (draft)

> **How did you approach each game, and did your strategy change?**
>
> I treated it as an optimization problem under uncertainty about who the other applicants are. I wrote an exact
> scorer for both games and unit-tested every tie case. I then simulated seven very different applicant
> populations: intuitive even or proportional splitters, concentrators, random players, computationally optimized
> players, a broad mix, and an adversarial field built to counter my own finalists. I chose allocations on one set
> of simulated applicants and judged them on a fresh set.
>
> In Game 1, the score against a fixed field adds up castle by castle, so I could compute the exact best response
> to each population. The allocation that maximized the average, [1, 1, 22, 35, 41], was fragile: about 11 points
> against intuitive players, but 7.3 against optimized ones. I chose [2, 3, 5, 37, 53] instead. It concedes
> castle 3, dominates castles 4 and 5, and scored between 8.8 and 9.2 in every population I modeled.
>
> Yes, my strategy changed for Game 2. With payouts of 9/4/2/0, finishing first matters far more than collecting
> points. Winning castles 3 and 4 outright (7 of 15 points) usually beats three opponents who split the rest, so
> I submit [0, 0, 39, 61, 0]. It came first about 70% of the time in simulation and held up against an optimizer
> searching for counters.
>
> I can't prove either allocation is optimal against the real pool. Blotto has no unbeatable pure strategy, and
> my self-play never converged. These are the most robust choices across the scenarios I could model.
