# GTA VI Trophy Rarity Forecast

![bounty](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)
![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/tuyullsxx1-cmd/gta6-trophy-rarity-forecast/rank.svg)
![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/tuyullsxx1-cmd/gta6-trophy-rarity-forecast/reward.svg)

Forecast how many GTA VI players earn each trophy in week one —
[make.fun bounty gta6-trophy-rarity-forecast-01](https://make.fun/bounty/gta6-trophy-rarity-forecast-01).

A single stdlib-only Python program (`main.py`, Python 3.13, no third-party
packages, no network, deterministic) that reads `$MAKEFUN_INPUT_DIR`
(else `/input/`) `*.in` JSON case files and writes `$MAKEFUN_OUTPUT_DIR`
(else `/output/`) `<id>.out` JSON:

```json
{"trophies": [{"id": 1, "q": [q05, q25, q50, q75, q95]}, ...]}
```

exactly one row per trophy, quantiles in percent 0–100, non-decreasing.
Runtime ~0.03 s per case (limit 8 s), output ~2.7 KB (limit 65,536 bytes).

## The model

Work in **earners and players, not raw rates**. A trophy's rate is
E_i / P, and Exophase's page is frozen between its own refreshes, so the
history is first cut into **refresh segments** (reads where the player count
or any rate changed). Each segment is one refresh's snapshot.

- **Players P(t):** a local log-log power law fitted on the last up-to-5
  refresh points, crossed with a linear-in-time second opinion from the
  recent per-hour growth, taking the larger, capped at 10× the last
  observed count. This tracks the launch wave without saturating the way a
  global log-time curve does. With no refresh ever observed (a flat
  launch-night history), a launch-wave prior calibrated on the kit's own
  facts: Exophase's first refresh multiplied the tracked players ~6× over
  ~4.7 h.
- **Earners E_i(t):** a **common-hazard model**, dE_i/dt = h_i(t)·(P − E_i).
  Between refreshes, the constant hazard that maps the interval's start
  state to its end state (with P linear in the interval) is recovered by
  bisection; each trophy's level is its recent hazard (smoothed over its
  last intervals) and the pooled log-slope of h over log-time across
  trophies is extrapolated forward. E_i is then integrated to the target
  on 0.25 h substeps against the extrapolated P(t). Because the hazard acts
  on the whole tracked pool — old cohort progressing *and* new joiners —
  the model keeps growing earners even when the player base stops growing
  (dilution alone would freeze the rate), and grows them faster than
  log-linear when the cohort reaches a trophy's difficulty window. With no
  refresh observed, the fallback is a marginal-cohort prior
  m_i = 1 − (1 − r_i)^ρ, where r_i is the regular cohort's rate after
  subtracting the reviewer core (the mode of the small earner counts),
  ρ ≈ 0.22 for launch night.
- **Spread (refresh-aware):** the logit-normal interval width grows with
  the size of the predicted move, the horizon, the sparsity of the history,
  and the Poisson noise on small earner counts, so the 90% band covers a
  refresh that lands early, late, or not at all. The opening trophy (100%
  in the last read) keeps a median near 100% with a widened lower tail.

## Why this shape

The dominant effect over the 6,510-minute final horizon is **refresh /
dilution**: the players denominator grows as new players arrive while
earners accumulate per refresh, so raw rates fall as the base dilutes.
Modelling the earners/players ratio — and correcting for dilution — is
what separates a forecast from a persistence baseline. The hazard model
was chosen over a marginal-cohort model (which can only grow earners via
new players and fails when the player base saturates) and over a
logit-linear rate trend (which extrapolates badly over 4.5 days); see
`EVAL-REPORT.md` for the head-to-head numbers.

## Run it

```sh
MAKEFUN_INPUT_DIR=path/to/cases MAKEFUN_OUTPUT_DIR=path/to/out python3 main.py
```

## Files

- `main.py` — the entrypoint (only file the grader runs).
- `EVAL-REPORT.md` — local evaluation: proxy scores, simulator scores,
  runtime, validity checks.
- `LICENSE` — MIT.
