# Evaluation report — gta6-trophy-rarity-forecast-01

There is no local grade for this bounty; the server grades every entry.
This report records the local evaluation that was done instead, so the
numbers are checkable and the limitations are stated plainly.

## Final model (round 2)

Hybrid median (`main.py`, stdlib only, deterministic): once the history
holds two or more refresh points, the median comes from a COHORT-DELAY
model -- every player earns a trophy a lognormal delay after they start
playing (median tau_i hours, shared log-spread 0.4); tau_i is fitted per
trophy by matching the model's earner count to the observed count at the
last refresh.  With a FLAT history (one refresh point) the median stays
with the round-1 models: the common-hazard ODE (once refreshes exist) and
the marginal-cohort prior (rho = 0.08, down from 0.22) when none do.
Spread is horizon-dependent: the whole spread is scaled by 0.5 at a
90-minute horizon rising to 0.8 at a 4.5-day horizon.

## Round 2 changes (19 Nov 2026, evening) -- what changed and why

Round 1 scored 0.181542 on the real practice cases (rank 531 of 3,224),
typical miss 0.04 pp, coverage 0.9818.  Diagnosis (simulator + the live
numbers): the median is close but the intervals are far too wide, and on
the long-horizon final case the round-1 median fails structurally on slow
trophies (simulator f00: median logit bias +2.5 to +3.0 on the eight
slowest trophies -- a trophy nobody has earned yet has hazard ~0, so the
hazard ODE leaves it at ~0 forever, while in truth the launch cohort
reaches its delay window over the forecast horizon and the trophy rises
10-14x).

1. **Cohort-delay median (multi-refresh histories).** E_i(t) = sum over
   start cohorts of cohort size x delay CDF at that cohort's lag.
   Simulator f00: 0.7732 -> 0.2946 pinball; worst world 0.8635 -> 0.3061;
   coverage 0.70 -> 0.89.  Robust to the tau draw (fresh random taus:
   f00 0.296 vs hazard 0.731) and to sigma 0.3/0.5 (f00 0.42/0.40, still
   far better than the hazard's 0.77).  A trajectory (all-refresh-points)
   tau fit was tried and rejected: same mean, worse worst world (0.355).
2. **Hybrid switch.** The delay fit is used only when k >= 2 refresh
   points.  On flat histories it is unidentified (it rests on the assumed
   anchor start distribution and reviewer count) and scores 0.49-0.61 on
   the simulator practice vs 0.21 for the hazard/marginal median -- even
   with the TRUE simulator parameters (n_rev, Weibull starts, sigma) it
   scores 0.51-0.61, because the simulator's practice answers are
   generated from random taus that contradict the real anchor counts
   (the sim's internal earner count at the anchor is ~1.2x the displayed
   one).  So the flat path keeps the round-1 median, which is validated
   on the REAL practice score (0.1815).
3. **Spread recalibration (horizon-dependent).** A spread-scale sweep
   showed practice wants ~0.5x the round-1 width (coverage 0.98 -> 0.94)
   while the final case wants ~0.75-0.8x (the simulator optimum is ~0.5x,
   but that trusts the delay median more than the real data warrants, so
   0.8x is kept as a safety margin).  Practice: 0.2121/0.2309 -> 0.1598/
   0.2016 on the simulator.
4. **rho 0.22 -> 0.08.** The flat-path marginal prior over-credited new
   joiners with earning over 90 minutes; the sweep is a flat plateau at
   0.05-0.10, so 0.08 is the plateau centre, not a knife-edge.  It does
   not touch the final case (the flat path is never used there).
5. **Bug found and fixed while building the delay model:** the first
   version subtracted the reviewer count from the fit target while the
   reviewer cohort stayed in the cohort list, so the fit used the
   reviewers' CDF to match the target and the practice medians collapsed
   to ~0.  The fit now targets the FULL observed count.

## Simulator evaluation, round 2 (same 5 worlds, same scorer)

| model | practice p00/p01 | f00 | MEAN | worst world |
|---|---|---|---|---|
| round 1 (hazard + marginal) | 0.2121 / 0.2309 | 0.7732 | 0.4054 | 0.4359 |
| **round 2 (hybrid)** | **0.1598 / 0.2016** | **0.2946** | **0.2187** | **0.2244** |

Coverage round 2: practice 0.94/0.92, f00 0.89.  Fresh tau draws
(2 extra worlds, different random trophy delays): round 2 MEAN 0.222,
f00 0.296 vs round 1 MEAN 0.393, f00 0.731 -- the improvement is not an
artefact of one tau draw.

Projected real practice score (if the round-1 real/sim ratio of 0.82
transfers): ~0.15, vs round 1's 0.1815.  That is a real move but NOT
toward the ~0.10 hoped for, and still far from the live top 10
(0.024-0.061).  The final case is the scored one, and there the
simulator says the model is ~2.6x better than round 1 -- but the
simulator is self-built, the delay model is in its own class, and no
local number predicts the real f00 score.  Honest assessment: round 2
is very likely to improve both the practice board and the final run
materially; it is not likely to reach the top 20 on practice alone.

## Final model (round 1, superseded)
refresh segmentation → local log-log power-law player curve → per-trophy
hazard recovered by bisection per interval, pooled log-slope extrapolated
→ E integrated to the target on 0.25 h substeps → refresh-aware
logit-normal spread. Flat-history fallback: marginal-cohort prior with
reviewer-core subtraction (ρ = 0.22).

## Simulator evaluation (the real evaluation)

A synthetic Exophase-refresh simulator was built from the facts
RULES.txt states: release 2026-11-18T11:00:00Z, Weibull launch wave
calibrated so P(12.83 h) = 638 and P(17.5 h) = 3,868 exactly, refreshes
every R hours, per-trophy hours-to-earn (story 0.05–130 h, platinum
350 h), player pace LogNormal(0, 0.35), 6 reviewers starting 500 h before
release. Five worlds were generated (β 6.5–9, refresh 3.5–6.5 h,
sustained tail 0–300k players), each with p00/p01 practice cases
(90-min horizon) and an f00 case (6,510-min horizon to 26 Nov 00:00 UTC).
Pinball loss on the logit scale (lower is better), mean over all trophies
× 5 quantiles; `typical_miss` is the median |answer − q50| in percentage
points; `cov90` is the share of answers inside q05–q95.

| world | practice p00/p01 | f00 | MEAN |
|---|---|---|---|
| sim1 (β7, R4.7h, tail 50k) | 0.213 / 0.232 | 0.753 | **0.399** |
| sim2 (β7, R4.7h, tail 0 — saturating) | 0.213 / 0.232 | 0.793 | **0.413** |
| sim3 (β7, R4.7h, tail 300k — huge growth) | 0.213 / 0.232 | 0.864 | **0.436** |
| sim4 (β9, R6.5h, tail 100k) | 0.207 / 0.223 | 0.748 | **0.393** |
| sim5 (β6.5, R3.5h, tail 100k) | 0.216 / 0.236 | 0.708 | **0.387** |
| **average of MEANs** | | | **0.405** |

Baselines on sim1 for comparison (same cases, same scorer):

| model | practice | f00 | MEAN |
|---|---|---|---|
| house starter (persistence + 0.5·√days spread) | 1.450 | 1.353 | 1.418 |
| naive (all quantiles = last rate) | 1.539 | 1.892 | 1.657 |
| **final model** | **0.213 / 0.232** | **0.753** | **0.399** |

The final model is ~3.5× better than the house baseline and ~4.2× better
than naive on the simulator mean. (RULES.txt states the house baseline
scores ~1.51 on the real practice cases; the simulator reproduces that
regime: 1.45.)

### Variant selection (same simulator, 5 worlds, MEAN of means)

| variant | avg MEAN | worst world |
|---|---|---|
| marginal-cohort integration | 0.684 | 1.618 (sim2) |
| **common-hazard ODE (chosen)** | **0.430** → **0.405 after spread tuning** | 0.436 |
| logit-linear rate trend | 1.076 | 1.855 |
| hazard + trend blend | 0.667 | 0.929 |

The marginal model fails catastrophically on the saturating world (it can
only grow earners via new players, so when P stops growing it predicts
rates freeze while the truth rises toward 100% as everyone finishes the
story). The trend model extrapolates badly over 4.5 days. Per-trophy
hazard slopes were tried and rejected (avg 0.500 — they overfit interval
noise; the pooled slope wins). Spread was tuned on the grid
S_MOVE/S_SPARSE_FEW/S_WALK: (0.5, 0.35, 0.5) → 0.430; (0.3, 0.25, 0.4)
→ 0.405 with the best worst-case coverage; narrower settings tie on loss
but collapse coverage on the saturating world, so the wider setting was
kept. RHO was checked at 0.1/0.22/0.4 (0.402/0.405/0.418); 0.22 was kept
because the gain at 0.1 is practice-only and the final case is the scored
one.

### Coverage

Practice cov90 ≈ 0.96–0.98 (slightly over-covering — the interval is a
touch wide on the 90-min horizon, a deliberate safety margin). f00 cov90
0.75–0.84 in four worlds, **0.31 in the saturating world (sim2)**: when
the player base stops growing and everyone finishes the story, the model
is overconfident about how fast the hard trophies rise. That world is the
known weak spot.

### Simulator caveats (honest)

The simulator is the author's own generative model, so it flatters any
model in its own class — the absolute numbers (0.40) should not be
compared directly to the live board (top 10 live: 0.059–0.080), which is
scored on real Exophase data. What the simulator establishes is the
*ordering* between variants and the *robustness* across launch-wave
shapes, not a predicted live score. The real f00 answer depends on the
actual launch-week player influx and refresh cadence, which no local
evaluation can see.

## Proxy evaluations on the real kit cases

**Proxy A — hold out the last read:** forecast the last read's time from
the earlier reads only, score pinball vs the held-out read.

| case | final model | naive (last rate) |
|---|---|---|
| p00 | 0.6655 | 0.0000 |
| p01 | 0.8033 | 0.0000 |

This proxy is **degenerate and does not discriminate the model**: the
real history is flat (every read identical — the page was frozen between
refreshes), so the held-out "answer" is just the last rate and persistence
scores 0 by construction. The model loses because its flat-history prior
predicts the dilution a refresh would bring over the 30-min window, and
no refresh happened in that window. The real p00/p01 targets *do* straddle
a refresh (RULES.txt: the 04:30 read shows 3,868 players vs 638 before),
which is why the simulator — which models refreshes — is the evaluation
that matters. The proxy validates the code path only.

**Proxy B — forecast p00's target, score against p01's earliest reads:**
impossible. p00's target is 2026-11-19T04:30:00Z; p01's history ends
2026-11-19T03:00:00.309Z. No timestamp overlap (checked from the case
files, not assumed).

## Validity checks (real kit cases p00/p01)

- Run: `MAKEFUN_INPUT_DIR=<kit>/input MAKEFUN_OUTPUT_DIR=<out> python3 main.py`
- Runtime: **0.067 s for both cases** (~0.03 s/case; limit 8 s/case).
- Determinism: two runs byte-identical (`diff -r` clean).
- Shape: 55 rows, ids 1–55, 5 quantiles each, non-decreasing, all in
  0–100. Output 2,782 bytes (p00) / 2,708 bytes (p01); limit 65,536.
- No third-party imports (stdlib only), no network access, no reads of
  any answer file (only the kit `*.in` files).

## Example forecasts (real p00, target 04:30 UTC, 90-min horizon)

Last read 02:30 UTC, 638 players. Dilution dominates: the refresh
multiplies the player base ~6× while earners grow slowly, so most rates
fall ~4–6×.

| id | trophy | last | q50 | q05–q95 |
|---|---|---|---|---|
| 1 | Vice Got a Price! (platinum) | 0.63% | 0.1054% | 0.0291–0.3808% |
| 2 | Just Like Paradise (bronze) | 100.00% | 99.9900% | 99.9281–99.9986% |
| 3 | Paradise Lost (bronze) | 1.25% | 0.2978% | 0.1129–0.7831% |
| 4 | T**s Ass Drug Money (bronze) | 1.10% | 0.2424% | 0.0869–0.6740% |
| 20 | Baited My Tackle (bronze) | 2.04% | 0.5751% | 0.2469–1.3338% |
| 55 | On the Spot (bronze) | 0.78% | 0.1318% | 0.0385–0.4496% |
