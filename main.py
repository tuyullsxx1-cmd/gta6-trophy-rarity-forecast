"""gta6-trophy-rarity-forecast-01: refresh-aware earners/players forecaster.

Model (standard library only, deterministic, CPU only):
  - Work in EARNERS and PLAYERS, not raw rates.  A trophy's rate is
    E_i / P, and Exophase's page is frozen between its own refreshes, so the
    history is first cut into refresh segments: reads where the player count
    or any rate changed.  Each segment is one refresh's snapshot.
  - PLAYERS P(t): a LOCAL log-log power law fitted on the last up-to-5
    refresh points (log P linear in log hours since the first read), crossed
    with a linear-in-time second opinion from the recent per-hour growth,
    taking the larger, capped at 10x the last observed count.  This tracks
    the launch wave without saturating the way a global log-time curve does.
    With no refresh ever observed (a flat launch-night history), fall back to
    a launch-wave prior calibrated on the kit's own facts: Exophase's first
    refresh multiplied the tracked players ~6x over ~4.7h.
  - EARNERS E_i(t) -- HYBRID median (round 2).  Once the history holds two
    or more refresh points, the median comes from a COHORT-DELAY model:
    every player earns trophy i a lognormal delay after they start playing
    (median tau_i hours, shared log-spread 0.4), so E_i(t) is the sum over
    start cohorts of cohort size times the delay CDF at that cohort's lag.
    tau_i is fitted per trophy by matching the model's earner count to the
    observed count at the last refresh.  This fixes the round-1 hazard
    model's structural failure on slow trophies: a trophy nobody has earned
    yet has hazard ~0, so the hazard ODE leaves it at ~0 forever, while in
    truth the launch cohort reaches its delay window over the forecast
    horizon and the trophy rises sharply.  With a FLAT history (one refresh
    point) the delay fit is unidentified -- it rests entirely on the assumed
    anchor start distribution and reviewer count -- so the median stays
    with the round-1 models: the common-hazard ODE (once refreshes exist)
    and the marginal-cohort prior (rho = 0.08) when none do.
  - The answer is the page as of Exophase's last refresh before the target, so
    the median is the post-refresh state E_i(T)/P(T), never the frozen last
    rate.  The spread is refresh-aware and HORIZON-DEPENDENT (round 2,
    narrowed in round 3): it grows with the size of the predicted move, the
    horizon, the sparsity of the history, and the Poisson noise on small
    earner counts, and the whole spread is scaled by 0.5 at a 90-minute
    horizon rising to 0.7 at a 4.5-day horizon (round 3: 0.7, down from 0.8
    -- the simulator says the long-horizon intervals over-cover, and the
    narrower width gains on every simulator family without moving the worst
    world; the practice answers are nearly deterministic once the refresh
    is modelled, so a full-width interval wastes pinball loss, while the
    week-one answer is genuinely uncertain).
  - Round 3: the delay median's tau is the geometric mean of the last-point
    fit and the trajectory fit (see fit_tau_traj), which tames the far-tail
    overprediction on slow trophies (platinum was +2.5 to +3.9 logit too
    high on the simulator) while holding the saturating world at the
    round-2 level.
  - Quantiles are a logit-normal around the median; the opening trophy (100%
    in the last read) keeps a median near 100 with a widened lower tail.

Reads $MAKEFUN_INPUT_DIR (else /input/) *.in, writes $MAKEFUN_OUTPUT_DIR
(else /output/) <id>.out as {"trophies": [{"id": n, "q": [q05, q25, q50, q75,
q95]}]}.  One run per case file, in name order, byte-identical across runs.
"""

import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# --- tunable model constants (see module docstring) ---
RHO = 0.08            # flat-history time-scaling exponent for marginal rates
                      # (round 2: 0.05-0.10 plateau on the simulator; 0.22
                      # over-credited new joiners with earning over 90 min)
PRIOR_G = 2.71        # flat-history log-time player-growth slope
PRIOR_TAU_H = 5.0     # flat-history log-time player-growth timescale (hours)
PRIOR_MULT_CAP = 8.0  # cap on the flat-history player multiplier
S_WALK = 0.4          # logit spread per sqrt(day) of horizon
S_MOVE = 0.3          # spread per logit unit of predicted move
S_SPARSE_FEW = 0.25   # extra spread with <3 refresh points
S_SPARSE_SOME = 0.15  # extra spread with <6 refresh points
S_COUNT_CAP = 0.6     # cap on the Poisson count-noise spread
S_MIN = 0.3
S_MAX = 1.5
S_NEAR100 = 1.2       # spread for a trophy whose median is >= 99.9%
# round 2: cohort-delay median (multi-refresh histories only)
DELAY_SIGMA = 0.4     # log-spread of the hours-to-earn distribution
DELAY_TAU_LO = 0.05   # bisection bounds on the fitted median delay (hours)
DELAY_TAU_HI = 2000.0
DELAY_ANCHOR_H = 12.83  # release -> first read (RULES.txt: 11:00 -> 23:50:49Z)
DELAY_REVIEWER_H = 500.0  # reviewers started this many hours before release
# round 3: horizon-dependent spread multiplier (0.5 at 90 min -> 0.7 at 4.5 d)
K_SPREAD_SHORT = 0.5
K_SPREAD_LONG = 0.7
K_SPREAD_TAU_D = 1.0  # days; multiplier = short + (long-short)*(1-exp(-d/tau))


def clamp(x, lo=0.01, hi=99.99):
    return min(hi, max(lo, x))


def logit(pct):
    p = clamp(pct) / 100.0
    return math.log(p / (1.0 - p))


def sigmoid(lg):
    if lg >= 0:
        return 100.0 / (1.0 + math.exp(-lg))
    e = math.exp(lg)
    return 100.0 * e / (1.0 + e)


def round4(x):
    """x rounded to 4 decimals, half up (as the starter rounds it)."""
    scaled = x * 10000
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000
    return int(value) if value == int(value) else value


def parse_time(s):
    """ISO 8601 UTC timestamp (with or without fractional seconds) -> hours
    since the Unix epoch."""
    import datetime
    dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt.timestamp() / 3600.0


def refresh_points(case):
    """Cut the history into refresh segments.

    Returns (times_h, players, earners, last_rates) where times_h are hours
    since the first read, players the tracked count per segment, earners a
    list per trophy of its earner count per segment, and last_rates the last
    read's rates (with nulls carried forward from earlier reads).
    """
    hist = case["history"]
    if not hist:
        raise ValueError("case has no history")
    t0 = parse_time(hist[0]["at"])
    n_tr = len(case["trophies"])
    # last non-null rate per trophy, carried forward
    last_rate = [None] * n_tr
    segments = []  # (t_h, players, [rates])
    prev_key = None
    for read in hist:
        rates = []
        for i, r in enumerate(read["rates"]):
            if r is not None:
                last_rate[i] = r
            rates.append(last_rate[i] if last_rate[i] is not None else 0.0)
        key = (read["players_tracked"], tuple(rates))
        if key != prev_key:
            segments.append((parse_time(read["at"]) - t0,
                             read["players_tracked"], rates))
            prev_key = key
    # earner counts per segment (rates are 2-decimal percents of integer counts)
    earners = []
    for _ in range(n_tr):
        earners.append([])
    for _, p, rates in segments:
        for i, r in enumerate(rates):
            earners[i].append(int(round(r * p / 100.0)))
    # consistency with the page's trophies_earned total: rescale only if far off
    last_total = hist[-1].get("trophies_earned")
    if last_total:
        s = sum(e[-1] for e in earners)
        if s > 0 and abs(s - last_total) > 0.02 * max(last_total, 1):
            f = last_total / s
            for i in range(n_tr):
                earners[i][-1] = int(round(earners[i][-1] * f))
    times = [s[0] for s in segments]
    players = [s[1] for s in segments]
    return times, players, earners, [s[2] for s in segments][-1]


def player_curve(times, players, t_last, t_target):
    """Predict P(t) for t in [t_last, t_target] on an hourly grid.

    Returns (times_grid, p_grid) including t_target as the final point.
    The launch tail keeps growing roughly as a power of time, so the
    extrapolation is LOCAL: a log-log power law fitted on the last few
    refresh points (and a linear-in-time extrapolation as a second opinion),
    never a global saturating fit.  With one point only, the launch-wave
    prior from the kit's own facts is used instead.
    """
    n = len(times)
    u = [math.log1p(t) for t in times]
    logp = [math.log(max(p, 1)) for p in players]
    if n == 1:
        coef = None
        gamma = None
    else:
        # local power law in t (not log-time): log P = a + gamma * log t,
        # fitted on the last up-to-5 refresh points (the recent regime)
        m = min(5, n)
        xs = [math.log(max(t, 1e-6)) for t in times[-m:]]
        ys = logp[-m:]
        mx = sum(xs) / m
        my = sum(ys) / m
        den = sum((x - mx) ** 2 for x in xs)
        gamma = (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
                 if den > 1e-9 else 0.0)
        gamma = min(max(gamma, 0.0), 2.5)
        coef = gamma
    # recent linear growth per hour (last interval), for the second opinion
    if n >= 2 and times[-1] > times[-2]:
        g_lin = (players[-1] - players[-2]) / (times[-1] - times[-2])
    else:
        g_lin = 0.0

    def logp_at(tt):
        uu = math.log1p(tt)
        if coef is None:
            # flat history: launch-wave prior from the kit's own facts.
            # The refresh at the target shows every player who joined since
            # the last refresh (at or before the first read), so the
            # multiplier is over the full span first-read -> target.
            accum = t_target - times[0]
            mult = math.exp(PRIOR_G * math.log1p(accum / PRIOR_TAU_H))
            mult = min(mult, PRIOR_MULT_CAP)
            if t_target > t_last:
                frac = (uu - u[-1]) / max(math.log1p(t_target) - u[-1], 1e-9)
                return logp[-1] + math.log(mult) * frac
            return logp[-1]
        return logp[-1] + coef * (math.log(max(tt, 1e-6)) - math.log(max(t_last, 1e-6)))

    # hourly grid from t_last to t_target
    grid_t = []
    t = t_last
    while t < t_target - 1e-9:
        grid_t.append(t)
        t += 1.0
    grid_t.append(t_target)
    grid_p = []
    for tt in grid_t:
        lp = logp_at(tt)
        p_pow = math.exp(lp)
        p_lin = players[-1] + max(g_lin, 0.0) * (tt - t_last)
        p = max(p_pow, p_lin) if coef is not None else p_pow
        p = min(p, players[-1] * 10.0)  # cap the multiplier at 10x
        grid_p.append(max(p, players[-1]))
    return grid_t, grid_p


def hazard_rates(times, players, earners):
    """Per-trophy earning hazard between refreshes.

    A common-hazard model: every tracked player who has not yet earned trophy
    i earns it at hazard h_i(t) per hour, so dE_i/dt = h_i * (P - E_i).
    For each interval the constant h that maps the interval's start state to
    its end state (with P linear in the interval) is found by bisection.
    Returns (levels, pooled_slope): levels[i] is trophy i's recent hazard
    (smoothed, geometric mean over its last intervals, or None), pooled_slope
    the shared log-slope of h over log-time across trophies (per-trophy
    slopes were tried and overfit the interval noise).
    """
    n_tr = len(earners)
    k = len(times)
    u = [math.log1p(t) for t in times]
    levels = []
    xs, ys = [], []
    for i in range(n_tr):
        hs = []
        for j in range(k - 1):
            dt = times[j + 1] - times[j]
            if dt <= 0:
                continue
            p0, p1 = players[j], players[j + 1]
            e0, e1 = earners[i][j], earners[i][j + 1]
            if e1 <= e0:
                hs.append((u[j + 1], 0.0))
                continue
            g = (p1 - p0) / dt
            # bisection on h: integrate dE/dt = h*(P(t)-E) with 0.25h steps
            def end_e(h):
                e = float(e0)
                t = 0.0
                step = 0.25
                while t < dt - 1e-9:
                    ds = min(step, dt - t)
                    pm = p0 + g * (t + ds / 2.0)
                    e += h * max(pm - e, 0.0) * ds
                    t += ds
                return e
            lo, hi = 0.0, 5.0
            if end_e(hi) < e1:
                hs.append((u[j + 1], hi))
                continue
            for _ in range(40):
                mid = (lo + hi) / 2.0
                if end_e(mid) < e1:
                    lo = mid
                else:
                    hi = mid
            hs.append((u[j + 1], (lo + hi) / 2.0))
        if not hs:
            levels.append(None)
            continue
        # smoothed level: geometric mean over the last three intervals
        w = [0.5, 0.3, 0.2]
        tot_w, tot = 0.0, 0.0
        for wi, (_, h) in zip(w, reversed(hs)):
            tot += wi * math.log(max(h, 1e-6))
            tot_w += wi
        levels.append(math.exp(tot / tot_w))
        for uu, h in hs:
            if h > 1e-4:
                xs.append(uu)
                ys.append(math.log(h))
    slope = 0.0
    if len(xs) >= 10:
        mx = sum(xs) / len(xs)
        my = sum(ys) / len(ys)
        den = sum((x - mx) ** 2 for x in xs)
        if den > 1e-9:
            slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
            slope = min(max(slope, -2.0), 3.0)
    return levels, slope


def phi(x):
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def delay_cohorts(times, players, grid_t, grid_p, n_rev):
    """Cohorts (start time, size) for the delay model.

    Times are hours since the first read.  The first read is DELAY_ANCHOR_H
    after release, so the anchor cohort started uniformly on
    [-DELAY_ANCHOR_H, 0]; it is split into 13 one-hour sub-cohorts.  Each
    later refresh interval's joiners start at the interval midpoint; the
    forecast grid's joiners likewise.  Reviewers (n_rev players) started
    DELAY_REVIEWER_H before release.
    """
    cohorts = []
    anchor = players[0]
    sub = anchor / 13.0
    for j in range(13):
        cohorts.append((-DELAY_ANCHOR_H + j + 0.5, sub))
    for j in range(len(times) - 1):
        dp = players[j + 1] - players[j]
        if dp > 0:
            cohorts.append(((times[j] + times[j + 1]) / 2.0, float(dp)))
    for j in range(len(grid_t) - 1):
        dp = grid_p[j + 1] - grid_p[j]
        if dp > 0:
            cohorts.append(((grid_t[j] + grid_t[j + 1]) / 2.0, float(dp)))
    if n_rev > 0:
        cohorts.append((-(DELAY_ANCHOR_H + DELAY_REVIEWER_H), float(n_rev)))
    return cohorts


def earners_at(cohorts, t, tau, sigma=DELAY_SIGMA):
    """Expected earners by time t for a trophy with lognormal delay
    (median tau hours, log-spread sigma) over the given cohorts."""
    if tau <= 0:
        return sum(n for _, n in cohorts)
    lt = math.log(tau)
    tot = 0.0
    for s, n in cohorts:
        lag = t - s
        if lag <= 0:
            continue
        tot += n * phi((math.log(lag) - lt) / sigma)
    return tot


def fit_tau(cohorts, t_last, e_target):
    """Median hours-to-earn tau whose cohort-delay model reproduces
    e_target earners at t_last (bisection on log tau; earners decrease in
    tau).  The target is the FULL observed count: the reviewer cohort is
    part of the cohort list, so it must not be subtracted from the target.
    e_target <= 0 is unidentified (no earner seen yet): return the lower
    bound tau that would produce ~1 earner, i.e. the smallest delay still
    consistent with (almost) nobody having earned it."""
    if e_target <= 0:
        e_target = 1.0
    lo, hi = math.log(DELAY_TAU_LO), math.log(DELAY_TAU_HI)
    if earners_at(cohorts, t_last, math.exp(lo)) <= e_target:
        return math.exp(lo)
    if earners_at(cohorts, t_last, math.exp(hi)) >= e_target:
        return math.exp(hi)
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if earners_at(cohorts, t_last, math.exp(mid)) > e_target:
            lo = mid
        else:
            hi = mid
    return math.exp((lo + hi) / 2.0)


def fit_tau_traj(cohorts, times, e_obs):
    """Fit tau by least squares over the whole refresh trajectory: minimize
    sum_j (E_model(t_j; tau) - E_obs_j)^2 / max(E_obs_j, 1) over log tau.
    Uses the trajectory shape, not just the last point, so a trophy whose
    count stayed flat while P grew pushes tau up -- the last-point fit
    alone leaves tau nearly unidentified for slow trophies (their count is
    ~the reviewer count at every refresh), and its far-tail prediction is
    exponentially sensitive to the fitted tau."""
    lo, hi = math.log(DELAY_TAU_LO), math.log(DELAY_TAU_HI)

    def loss(lt):
        tau = math.exp(lt)
        tot = 0.0
        for t, e in zip(times, e_obs):
            if e <= 0:
                continue
            d = earners_at(cohorts, t, tau) - e
            tot += d * d / max(e, 1.0)
        return tot

    gr = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = lo, hi
    c, d = b - gr * (b - a), a + gr * (b - a)
    fc, fd = loss(c), loss(d)
    for _ in range(50):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - gr * (b - a)
            fc = loss(c)
        else:
            a, c, fc = c, d, fd
            d = a + gr * (b - a)
            fd = loss(d)
    return math.exp((a + b) / 2.0)


def marginal_rates(times, players, earners):
    """Per-trophy marginal cohort earn rates between refreshes.

    Returns (levels, pooled_slope): levels[i] is trophy i's recent marginal
    rate (smoothed over its last intervals, or None), pooled_slope the shared
    log-slope of m over log-time across trophies (0 when unidentified).
    """
    n_tr = len(earners)
    k = len(times)
    u = [math.log1p(t) for t in times]
    levels = []
    xs, ys = [], []
    for i in range(n_tr):
        ms = []
        for j in range(k - 1):
            dp = players[j + 1] - players[j]
            if dp > 0:
                m = (earners[i][j + 1] - earners[i][j]) / dp
                ms.append((u[j + 1], min(max(m, 0.0), 1.0)))
        if not ms:
            levels.append(None)
            continue
        # smoothed level: weights 0.5/0.3/0.2 over the last three intervals
        w = [0.5, 0.3, 0.2]
        tot_w, tot = 0.0, 0.0
        for wi, (_, m) in zip(w, reversed(ms)):
            tot += wi * m
            tot_w += wi
        levels.append(tot / tot_w)
        for uu, m in ms:
            if m > 1e-4:
                xs.append(uu)
                ys.append(math.log(m))
    slope = 0.0
    if len(xs) >= 10:
        mx = sum(xs) / len(xs)
        my = sum(ys) / len(ys)
        den = sum((x - mx) ** 2 for x in xs)
        if den > 1e-9:
            slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
            slope = min(max(slope, -1.0), 1.0)
    return levels, slope


def forecast_case(case):
    if case["levels"] != LEVELS:
        raise ValueError("levels differ from the scored levels")
    times, players, earners, last_rates = refresh_points(case)
    t_last = times[-1]
    t_target = parse_time(case["target"]) - parse_time(case["history"][0]["at"])
    horizon_days = case["horizon_minutes"] / 1440.0
    n_tr = len(case["trophies"])
    k = len(times)

    grid_t, grid_p = player_curve(times, players, t_last, t_target)
    p_target = grid_p[-1]
    u_last = math.log1p(t_last)
    flat = (k == 1)
    # Reviewer core (flat history only): the deep-progress players who earned
    # the hard trophies before launch.  Their count is the most common small
    # earner count across trophies (the mode of the single-digit counts);
    # new players are regulars, so the prior is built on the regular cohort's
    # rate (earners minus reviewers, over players minus reviewers), not the
    # blended rate -- the blended rate would credit new players with the
    # reviewers' weeks of exposure.
    n_rev = 0
    if flat:
        from collections import Counter
        counts = Counter(earners[i][-1] for i in range(n_tr)
                         if 0 < earners[i][-1] < players[-1])
        if counts:
            n_rev = counts.most_common(1)[0][0]

    # Marginal-cohort integration (flat-history fallback only).
    levels_m, slope_m = marginal_rates(times, players, earners)
    # Common-hazard ODE (the forecaster once refreshes exist).
    levels_h, slope_h = hazard_rates(times, players, earners)

    def median_marg(i):
        r_last = last_rates[i]
        e_last = earners[i][-1]
        if levels_m[i] is not None:
            m0 = levels_m[i]
        elif flat:
            r_reg = max(e_last - n_rev, 0) / max(players[-1] - n_rev, 1)
            m0 = 1.0 - (1.0 - r_reg) ** RHO
        else:
            m0 = 0.0
        e_t = float(e_last)
        for j in range(len(grid_t) - 1):
            dp = grid_p[j + 1] - grid_p[j]
            if dp <= 0:
                continue
            uu = math.log1p(grid_t[j])
            m = m0 * math.exp(slope_m * (uu - u_last)) if levels_m[i] is not None else m0
            m = min(max(m, 0.0), 1.0)
            e_t += m * dp
        return clamp(100.0 * e_t / p_target) if p_target > 0 else r_last, e_t

    def median_haz(i):
        e_last = earners[i][-1]
        if levels_h[i] is not None:
            h0 = levels_h[i]
        elif flat:
            return median_marg(i)
        else:
            h0 = 0.0
        e_t = float(e_last)
        # integrate dE/dt = h(t) * (P(t) - E) on 0.25h substeps
        for j in range(len(grid_t) - 1):
            t_a, t_b = grid_t[j], grid_t[j + 1]
            p_a, p_b = grid_p[j], grid_p[j + 1]
            if t_b <= t_a:
                continue
            n_sub = max(1, int(round((t_b - t_a) / 0.25)))
            for s in range(n_sub):
                f0 = s / n_sub
                f1 = (s + 1) / n_sub
                tt = t_a + (f0 + f1) / 2.0 * (t_b - t_a)
                pm = p_a + (p_b - p_a) * (f0 + f1) / 2.0
                uu = math.log1p(tt)
                h = h0 * math.exp(slope_h * (uu - u_last))
                h = min(max(h, 0.0), 5.0)
                dt = (t_b - t_a) / n_sub
                e_t += h * max(pm - e_t, 0.0) * dt
        return clamp(100.0 * e_t / p_target) if p_target > 0 else last_rates[i], e_t

    # --- cohort-delay median (round 2; multi-refresh histories only) ---
    # tau_i is fitted per trophy to the FULL observed earner count at the
    # last refresh.  The reviewer count is the mode of the small earner
    # counts at the anchor segment (the deep-progress players who earned
    # the hard trophies before launch).
    # Round 3: tau_i is the GEOMETRIC MEAN of the last-point fit and the
    # trajectory fit (fit_tau_traj).  The last-point fit alone leaves tau
    # nearly unidentified for slow trophies -- their count is ~the reviewer
    # count at every refresh, so the fit lands wherever the tiny regular
    # contribution matches, and the far-tail prediction at the target is
    # exponentially sensitive to that tau (platinum was overpredicted by
    # +2.5 to +3.9 logit on the simulator).  The trajectory fit uses the
    # flat count history to push tau up; the geometric mean keeps its
    # gain while holding the worst world at the round-2 level (the pure
    # trajectory fit regresses the saturating world).
    delay_meds = None
    if k >= 2:
        from collections import Counter as _Counter
        _counts = _Counter(earners[i][0] for i in range(n_tr)
                           if 0 < earners[i][0] < 15)
        n_rev_d = _counts.most_common(1)[0][0] if _counts else 0
        _cohorts = delay_cohorts(times, players, grid_t, grid_p, n_rev_d)
        delay_meds = []
        for i in range(n_tr):
            _t_last = fit_tau(_cohorts, t_last, float(earners[i][-1]))
            _t_traj = fit_tau_traj(_cohorts, times, earners[i])
            tau_i = math.sqrt(_t_last * _t_traj)
            e_t = earners_at(_cohorts, t_target, tau_i)
            delay_meds.append((clamp(100.0 * e_t / p_target) if p_target > 0
                               else last_rates[i], e_t))

    rows = []
    for i, trophy in enumerate(case["trophies"]):
        r_last = last_rates[i]
        e_last = earners[i][-1]
        if flat:
            r_med, e_t = median_marg(i)
        elif delay_meds is not None:
            r_med, e_t = delay_meds[i]
        else:
            r_med, e_t = median_haz(i)
        # spread (logit units)
        move = abs(logit(r_med) - logit(r_last))
        s_walk = S_WALK * math.sqrt(max(horizon_days, 0.0))
        s_move = S_MOVE * move
        s_sparse = S_SPARSE_FEW if k < 3 else (S_SPARSE_SOME if k < 6 else 0.0)
        s_count = math.sqrt(1.0 / max(e_t, 1.0) + 1.0 / max(p_target - e_t, 1.0))
        s_count = min(s_count, S_COUNT_CAP)
        s = math.sqrt(s_walk ** 2 + s_move ** 2 + s_sparse ** 2 + s_count ** 2)
        s = min(max(s, S_MIN), S_MAX)
        # horizon-dependent multiplier (round 2): the practice answer is
        # nearly deterministic once the refresh is modelled, so a
        # full-width interval wastes pinball loss; the week-one answer is
        # genuinely uncertain, so the multiplier rises toward K_SPREAD_LONG
        # instead of collapsing to the simulator optimum (~0.5), which
        # would trust the delay median more than the real data warrants.
        _m = (K_SPREAD_SHORT + (K_SPREAD_LONG - K_SPREAD_SHORT)
              * (1.0 - math.exp(-max(horizon_days, 0.0) / K_SPREAD_TAU_D)))
        s = min(max(s * _m, 0.05), 3.0)
        if r_med >= 99.9:
            s = max(s, S_NEAR100)
        lg = logit(r_med)
        q = [round4(sigmoid(lg + z * s)) for z in Z]
        # keep the row non-decreasing after rounding
        for j in range(1, 5):
            if q[j] < q[j - 1]:
                q[j] = q[j - 1]
        rows.append({"id": trophy["id"], "q": q})
    return {"trophies": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
