"""SIP engine tests — fast path vs an independent brute-force implementation.

Run: python3 tests/test_sip.py   (uses the local store; skips if absent)

The bug this guards against: accumulating instalments per tenure instead of per
(tenure, day-of-month) multiplied every SIP by the number of day choices (12
instalments became 60) while every XIRR still looked plausible.
"""
import bisect
import datetime as dt
import os
import statistics
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import sip as S  # noqa: E402

DB = os.path.join(ROOT, "pipeline", "cache", "nav.sqlite")


def reference_plan(pts, end_day, years, dom, amount=1000.0):
    """Deliberately naive re-implementation: month loop, no shared helpers."""
    days = [d for d, _ in pts]
    navs = [v for _, v in pts]
    start = end_day - int(round(years * 365.25))
    d0 = S.EPOCH + dt.timedelta(days=start)
    d_end = S.EPOCH + dt.timedelta(days=end_day)
    y, m = d0.year, d0.month
    cash, units, invested, n = [], 0.0, 0.0, 0
    while (y, m) <= (d_end.year, d_end.month):
        mlen = (dt.date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
                - dt.timedelta(days=1)).day
        i = bisect.bisect_left(days, (dt.date(y, m, min(dom, mlen)) - S.EPOCH).days)
        if i < len(days):
            bd = days[i]
            b = S.EPOCH + dt.timedelta(days=bd)
            if (b.year, b.month) == (y, m) and start <= bd <= end_day:
                invested += amount
                units += amount / navs[i]
                n += 1
                cash.append((bd, -amount))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    if invested <= 0:
        return None, None, 0
    final = navs[bisect.bisect_right(days, end_day) - 1]
    value = units * final
    r = S.xirr(cash + [(end_day, value)])
    return (None if r is None else int(round(r * 1000))), int(round(value / invested * 1000)), n


def test_invariants():
    fails = 0
    # regular monthly SIP: instalment count must equal the number of months
    pts, end = _real_series()
    if not pts:
        print("SKIP invariants (no store)")
        return 0
    grid = S.plan(pts, end)
    assert grid is not None
    for si, years in enumerate(S.STARTS):
        for di, dom in enumerate(S.DAYS):
            n = grid["n"][si][di]
            lo, hi = int(years * 12) - 2, int(years * 12) + 2
            if n and not (lo <= n <= hi):
                print(f"FAIL instalment count {years}Y dom={dom}: {n}, expected ~{years * 12}")
                fails += 1
    if fails == 0:
        print(f"PASS instalment counts match tenure (12/36/60/120±2)")
    return fails


def test_against_reference():
    pts, end = _real_series()
    if not pts:
        print("SKIP reference comparison (no store)")
        return 0
    grid = S.plan(pts, end)
    assert grid is not None
    bad = 0
    for si, years in enumerate(S.STARTS):
        for di, dom in enumerate(S.DAYS):
            want = reference_plan(pts, end, years, dom)
            got = (grid["x"][si][di], grid["v"][si][di], grid["n"][si][di])
            if want != got:
                bad += 1
                print(f"FAIL {years}Y dom={dom}: fast={got} ref={want}")
    print(f"{'PASS' if bad == 0 else 'FAIL'} all {len(S.STARTS) * len(S.DAYS)} cells match the independent implementation")
    return bad


def test_npv_root():
    pts, end = _real_series()
    if not pts:
        print("SKIP npv (no store)")
        return 0
    days = [d for d, _ in pts]
    navs = [v for _, v in pts]
    start = end - int(round(5 * 365.25))
    cash, units = [], 0.0
    for (y, m) in S._months(start, end):
        mlen = S._last_day_of_month(y, m)
        i = bisect.bisect_left(days, (dt.date(y, m, min(5, mlen)) - S.EPOCH).days)
        bd = days[i]
        b = S.EPOCH + dt.timedelta(days=bd)
        if (b.year, b.month) == (y, m) and bd >= start:
            cash.append((bd, -1000.0))
            units += 1000.0 / navs[i]
    value = units * navs[bisect.bisect_right(days, end) - 1]
    cfs = cash + [(end, value)]
    r = S.xirr(cfs)
    assert r is not None
    npv = sum(a / (1 + r) ** ((d - cfs[0][0]) / 365.0) for d, a in cfs)
    ok = abs(npv) < 1e-3
    print(f"{'PASS' if ok else 'FAIL'} XIRR solves to NPV≈0 (residual {npv:.6f} on ₹{abs(value):,.0f})")
    return 0 if ok else 1


def test_edge_cases():
    fails = 0
    cases = [
        ("no sign change", S.xirr([(0, -100.0), (365, -100.0)]), None),
        ("single flow", S.xirr([(0, -100.0)]), None),
        ("zero terminal value", S.xirr([(0, -100.0), (365, 0.0)]), None),
    ]
    for label, got, want in cases:
        if got != want:
            print(f"FAIL {label}: {got} != {want}")
            fails += 1
    if fails == 0:
        print("PASS degenerate cash flows return n/a instead of a wrong root")

    # scheme with too little history must produce empty cells, not zeros
    thin = [(1000 + i, 10.0 + i * 0.01) for i in range(5)]
    g = S.plan(thin, thin[-1][0])
    assert g is not None
    if any(c is not None for row in g["x"] for c in row):
        print("FAIL thin series produced an annualised SIP rate")
        fails += 1
    else:
        print("PASS thin series yields no annualised rate (span guard)")
    # and it must be flagged as a late start rather than silently relabelled
    if all(f > 40 for f in g["f"][0] if f):
        print("PASS late start recorded in f[] so the UI can label the real window")
    else:
        print("FAIL late start not recorded:", g["f"])
    return fails


def _real_series():
    if not os.path.exists(DB):
        return [], 0
    db = sqlite3.connect(DB)
    end = db.execute("select max(day) from nav").fetchone()[0]
    if end is None:
        return [], 0
    code = db.execute("""select code from nav group by code
                         having count(*) > 2000 order by code limit 1""").fetchone()
    if not code:
        return [], 0
    pts = [(d, v) for d, v in db.execute("select day,nav from nav where code=? order by day", (code[0],)) if v]
    return pts, end


def run():
    print(f"SIP engine — {len(S.STARTS)} tenures x {len(S.DAYS)} days\n")
    fails = 0
    fails += test_against_reference()
    fails += test_invariants()
    fails += test_npv_root()
    fails += test_edge_cases()
    print(f"\n{'OK' if fails == 0 else str(fails) + ' FAILURES'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(run())
