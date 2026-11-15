"""SIP simulation over AMFI daily NAV history.

Design notes
------------
* A SIP instalment buys at the **first NAV published on or after** the chosen day of
  the month. If a month has no NAV at all (fund not yet launched, or a gap), that
  instalment is skipped rather than silently back-dated.
* XIRR is money-weighted and **scale invariant**: the same rate holds for any amount,
  so the grid is precomputed once and the UI can serve any rupee figure the user types.
* Solve with Newton, fall back to bisection. Return None when the cash flows have no
  sign change - a wrong root is worse than "n/a".
* Dates are integer days since 1970-01-01, matching the store.
"""
import bisect
import datetime as dt

EPOCH = dt.date(1970, 1, 1)
DEFAULT_AMOUNT = 1000.0

# start tenures (years back from as-of) and day-of-month choices
STARTS = [1, 3, 5, 10]
DAYS = [1, 5, 10, 15, 25]

# A single instalment is not a SIP: annualising one short window produces absurd
# numbers (a 4-day holding reported as a 400% XIRR). Require a real series.
MIN_INSTALMENTS = 2
MIN_SPAN_DAYS = 60


def _months(start_day: int, end_day: int):
    """Yield (year, month) from the month of start_day through the month of end_day."""
    d = EPOCH + dt.timedelta(days=start_day)
    y, m = d.year, d.month
    e = EPOCH + dt.timedelta(days=end_day)
    while (y, m) <= (e.year, e.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _last_day_of_month(y: int, m: int) -> int:
    nxt = dt.date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
    return (nxt - dt.timedelta(days=1)).day


def xirr(cfs):
    """cfs: [(day, amount)] with negative = invested, positive = terminal value."""
    if len(cfs) < 2:
        return None
    t0 = cfs[0][0]
    span = max(1.0, float(cfs[-1][0] - t0))

    def npv(r):
        return sum(a / (1.0 + r) ** ((d - t0) / 365.0) for d, a in cfs)

    def npv_d(r):
        s = 0.0
        for d, a in cfs:
            e = (d - t0) / 365.0
            disc = (1.0 + r) ** e
            s += -e * a / (disc * (1.0 + r))
        return s

    r = 0.12
    for _ in range(40):
        try:
            f, fd = npv(r), npv_d(r)
        except (OverflowError, ZeroDivisionError):
            break
        if fd == 0 or abs(f) < 1e-6:
            return r if abs(npv(r)) < 1e-4 else None
        step = f / fd
        nxt = r - step
        if nxt <= -0.9999 or nxt > 10.0:
            break
        if abs(nxt - r) < 1e-10:
            return nxt
        r = nxt

    # bisection fallback
    lo, hi = -0.9999, 10.0
    flo, fhi = npv(lo), npv(hi)
    if flo * fhi > 0:
        return None
    for _ in range(120):
        mid = (lo + hi) / 2.0
        fm = npv(mid)
        if abs(fm) < 1e-6:
            return mid
        if flo * fm <= 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2.0


def plan(pts, end_day: int, amount: float = DEFAULT_AMOUNT):
    """Run the SIP grid for one scheme.

    pts: [(day, nav)] ascending, daily, already restricted to <= end_day.
    Returns {"x": [[xirr_tenths]*len(DAYS)]*len(STARTS),
             "v": [[ratio_thousandths]...],
             "n": [[instalments]...],
             "f": [[days the first instalment landed after the nominal start]...]}
    Cells are None when the scheme had no data for that configuration.
    """
    days = [d for d, _ in pts]
    navs = [n for _, n in pts]
    if not days:
        return None

    # terminal NAV = last published at or before as-of
    k = bisect.bisect_right(days, end_day) - 1
    if k < 0:
        return None
    final_nav = navs[k]
    if not final_nav or final_nav <= 0:
        return None

    starts = list(STARTS)
    start_days = {s: end_day - int(round(s * 365.25)) for s in starts}

    # accumulators are keyed by (tenure, day-of-month): one cell is one schedule,
    # and summing across the five days silently multiplied every instalment by five
    keys = [(s, d) for s in starts for d in DAYS]
    invested = {k: 0.0 for k in keys}
    units = {k: 0.0 for k in keys}
    n_inst = {k: 0 for k in keys}
    first_buy = {k: None for k in keys}
    cash = {k: [] for k in keys}

    first_month = min(start_days.values())
    for (y, m) in _months(first_month, end_day):
        mlen = _last_day_of_month(y, m)
        for dom in DAYS:
            target = (dt.date(y, m, min(dom, mlen)) - EPOCH).days
            i = bisect.bisect_left(days, target)
            if i >= len(days):
                continue
            buy_day = days[i]
            d_buy = EPOCH + dt.timedelta(days=buy_day)
            if (d_buy.year, d_buy.month) != (y, m):
                continue                      # month had no NAV - skip, do not back-date
            if buy_day > end_day:
                continue
            price = navs[i]
            if not price or price <= 0:
                continue
            for s in starts:
                if buy_day < start_days[s]:
                    continue
                key = (s, dom)
                invested[key] += amount
                units[key] += amount / price
                n_inst[key] += 1
                if first_buy[key] is None:
                    first_buy[key] = buy_day
                cash[key].append((buy_day, -amount))

    x_out, v_out, n_out, f_out = [], [], [], []
    for s in starts:
        xr_row, vr_row, nr_row, fr_row = [], [], [], []
        for dom in DAYS:
            key = (s, dom)
            inv, un, fb = invested[key], units[key], first_buy[key]
            if inv <= 0 or n_inst[key] < MIN_INSTALMENTS or fb is None:
                xr_row.append(None); vr_row.append(None); nr_row.append(0); fr_row.append(0)
                continue
            span = end_day - fb
            # "late start": the fund's history (or its launch) began after the nominal
            # window opened, so this is not really a <tenure> SIP - the UI must say so
            late = max(0, fb - start_days[s])
            value = un * final_nav
            ratio = value / inv
            r = None
            if span >= MIN_SPAN_DAYS:
                r = xirr(list(cash[key]) + [(end_day, value)])
            xr_row.append(None if r is None else int(round(r * 1000)))
            vr_row.append(int(round(ratio * 1000)))
            nr_row.append(n_inst[key])
            fr_row.append(int(min(late, 9999)))
        x_out.append(xr_row); v_out.append(vr_row); n_out.append(nr_row); f_out.append(fr_row)
    return {"x": x_out, "v": v_out, "n": n_out, "f": f_out}


def calendar_years(pts, end_day: int):
    """Simple calendar-year returns keyed by year (last NAV of each year vs prior year)."""
    out = {}
    if not pts:
        return out
    days = [d for d, _ in pts]
    navs = [n for _, n in pts]
    years = sorted({(EPOCH + dt.timedelta(days=d)).year for d in days})
    prev = None
    for y in years:
        cutoff = (dt.date(y, 12, 31) - EPOCH).days
        i = bisect.bisect_right(days, min(cutoff, end_day)) - 1
        if i < 0:
            continue
        nav = navs[i]
        if prev and prev > 0 and nav:
            out[y] = round((nav / prev - 1.0) * 100.0, 2)
        prev = nav
    return out
