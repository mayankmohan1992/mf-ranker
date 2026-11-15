"""Turns the NAV store into the static dataset the dashboard reads.

Products per scheme, per week (Friday grid):

  * trailing return for 1W / 1M / 3M / 6M / 1Y / 3Y / 5Y / 10Y
    (absolute for windows < 1Y, CAGR for 1Y and longer)
  * rank within (SEBI category, plan[, benchmark group for index funds/ETFs])

Rank history is stored as one weekly series and re-sampled by the UI into
weekly / monthly / quarterly / half-yearly / annual views, so all five bases
come from a single consistent source and cannot disagree with each other.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil

from . import categories

WINDOWS = [
    ("1W", 7, "1 Week"),
    ("1M", 30, "1 Month"),
    ("3M", 91, "3 Months"),
    ("6M", 182, "6 Months"),
    ("1Y", 365, "1 Year"),
    ("3Y", 1095, "3 Years"),
    ("5Y", 1825, "5 Years"),
    ("10Y", 3650, "10 Years"),
]
WIN_DAYS = {k: d for k, d, _ in WINDOWS}
NAV_SERIES_WEEKS = 522   # ~10 years of weekly NAV points for the NAV chart
RANK_SERIES_WEEKS = 156  # ~3 years of weekly rank points for the rank chart
SAMPLE_TOLERANCE = 12    # days a weekly sample may drift from the exact Friday
MAX_STALE = 30           # a NAV older than this is treated as "scheme stopped reporting"


def _weekly_grid(end_day: int, weeks: int):
    """Fridays ending at/before end_day, oldest first. The last point is end_day itself."""
    end = dt.date(1970, 1, 1) + dt.timedelta(days=end_day)
    friday = end - dt.timedelta(days=(end.weekday() - 4) % 7)
    days = []
    for i in range(weeks - 1, -1, -1):
        days.append(friday - dt.timedelta(days=7 * i))
    if end != friday:
        days[-1] = end  # make the newest point "as of" the latest NAV date
    return [(d - dt.date(1970, 1, 1)).days for d in days]


def _sample(points, grid, max_stale=MAX_STALE):
    """points: sorted [(day, nav)] -> NAV per grid slot, "as of" that date.

    A scheme that stopped publishing (merged, closed, renamed to a new code) must
    NOT be forward-filled forever: a flat-lined dead fund would keep taking part
    in rankings and inflate every peer's group size. Beyond `max_stale` days the
    sample becomes None and the scheme simply drops out.
    """
    out = [None] * len(grid)
    j = 0
    last_nav = None
    last_day = None
    for i, g in enumerate(grid):
        while j < len(points) and points[j][0] <= g:
            last_day, last_nav = points[j]
            j += 1
        if last_nav is not None and last_day is not None and g - last_day <= max_stale:
            out[i] = last_nav
        else:
            out[i] = None
    return out


def _return_pct(v_now, v_then, days):
    if not v_now or not v_then or v_then <= 0 or days <= 0:
        return None
    ratio = v_now / v_then
    if days >= 365:
        return round((ratio ** (365.25 / days) - 1.0) * 100.0, 2)
    return round((ratio - 1.0) * 100.0, 2)


WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def _copy_site(dist_dir: str) -> None:
    """Copy the hand-written static assets next to the generated data."""
    os.makedirs(dist_dir, exist_ok=True)
    for name in os.listdir(WEB_DIR):
        src = os.path.join(WEB_DIR, name)
        dst = os.path.join(dist_dir, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


def build(store, dist_dir: str) -> dict:
    _copy_site(dist_dir)
    end_day = store.max_day()
    if end_day is None:
        raise SystemExit("store is empty - run backfill/daily first")

    nav_grid = _weekly_grid(end_day, NAV_SERIES_WEEKS)
    rank_grid = nav_grid[-RANK_SERIES_WEEKS:]
    rank_offset = len(nav_grid) - len(rank_grid)
    rank_index = {g: i for i, g in enumerate(rank_grid)}

    schemes = {s["code"]: s for s in store.schemes()}
    series = {}
    for code, pts in store.series():
        if code not in schemes:
            continue
        series[code] = _sample(pts, nav_grid)

    dates = [(dt.date(1970, 1, 1) + dt.timedelta(days=g)).isoformat() for g in nav_grid]

    # ---- trailing returns on the weekly grid --------------------------------
    # rets[code][window] = list aligned to nav_grid
    rets = {}
    for code, navs in series.items():
        per = {}
        for key, days, _ in WINDOWS:
            vals = [None] * len(nav_grid)
            for i in range(len(nav_grid)):
                if navs[i] is None:
                    continue
                target = nav_grid[i] - days
                # find nearest grid slot at or before target
                j = i
                while j >= 0 and nav_grid[j] > target:
                    j -= 1
                if j < 0 or navs[j] is None:
                    continue
                if abs(nav_grid[j] - target) > max(SAMPLE_TOLERANCE, 9):
                    continue
                actual_days = nav_grid[i] - nav_grid[j]
                val = _return_pct(navs[i], navs[j], actual_days)
                if val is not None:
                    vals[i] = val
            per[key] = vals
        rets[code] = per

    # ---- rank within (category, plan, rank-group) ---------------------------
    groups = {}
    for code, meta in schemes.items():
        if code not in rets:
            continue
        key = (meta["category"], meta["plan"], meta["rgroup"] or "")
        groups.setdefault(key, []).append(code)

    ranks = {code: {k: [None] * len(rank_grid) for k, _, _ in WINDOWS} for code in schemes}
    group_sizes = {code: {} for code in schemes}

    for key, codes in groups.items():
        if len(codes) < 1:
            continue
        for wi, (wk, _, _) in enumerate(WINDOWS):
            for ri, nav_i in enumerate(range(rank_offset, len(nav_grid))):
                pairs = []
                for code in codes:
                    val = rets[code][wk][nav_i]
                    if val is not None:
                        pairs.append((val, code))
                if len(pairs) < 2:
                    continue
                pairs.sort(key=lambda p: (-p[0], p[1]))
                total = len(pairs)
                for pos, (_, code) in enumerate(pairs, start=1):
                    ranks[code][wk][ri] = pos
                    group_sizes[code][wk] = total

    # ---- emit --------------------------------------------------------------
    data_dir = os.path.join(dist_dir, "data")
    cat_dir = os.path.join(data_dir, "cat")
    ser_dir = os.path.join(data_dir, "s")
    for d in (cat_dir, ser_dir):
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d, exist_ok=True)

    # Schemes whose NAV stopped updating (merged / closed / renamed codes) stay in
    # the store for history but are not published - they would otherwise ship
    # thousands of all-null series and pollute the category counts.
    ACTIVE_DAYS = 45
    by_cat = {}
    for code, meta in schemes.items():
        if code not in rets:
            continue
        if meta["last_day"] is None or meta["last_day"] < end_day - ACTIVE_DAYS:
            continue
        by_cat.setdefault(meta["category"], []).append(code)

    def enc_rank(v):
        return 0 if v is None else v          # 0 is never a valid rank -> cheap null

    cat_index = []
    latest_i = len(nav_grid) - 1
    for canon in sorted(by_cat, key=lambda c: (categories.order_of(c), c)):
        codes = by_cat[canon]
        rows = []
        for code in sorted(codes, key=lambda c: schemes[c]["name"]):
            meta = schemes[code]
            latest_ret, latest_rank, latest_total, delta = {}, {}, {}, {}
            for key, _, _ in WINDOWS:
                latest_ret[key] = rets[code][key][latest_i]
                hist = ranks[code][key]
                r_last = r_prev = None
                for i in range(len(hist) - 1, -1, -1):
                    if hist[i] is not None:
                        r_last = hist[i]
                        for j in range(i - 1, -1, -1):
                            if hist[j] is not None:
                                r_prev = hist[j]
                                break
                        break
                latest_rank[key] = r_last
                latest_total[key] = group_sizes[code].get(key)
                delta[key] = None if (r_last is None or r_prev is None) else r_prev - r_last

            # per-scheme series file: NAV history + rank history, fetched on click
            navs = series[code]
            payload = {
                "c": code,
                "v": [0 if v is None else round(v, 4) for v in navs],
                "h": {k: [enc_rank(x) for x in ranks[code][k]] for k, _, _ in WINDOWS},
            }
            with open(os.path.join(ser_dir, code + ".json"), "w") as fh:
                json.dump(payload, fh, separators=(",", ":"))

            rows.append(
                {
                    "c": code,
                    "n": meta["name"],
                    "a": meta["amc"],
                    "p": meta["plan"],
                    "g": meta["rgroup"] or "",
                    "r": latest_ret,
                    "k": latest_rank,
                    "N": latest_total,
                    "d": delta,
                }
            )
        payload = {
            "name": canon,
            "asset": categories.asset_class(canon),
            "count": len(rows),
            "schemes": rows,
        }
        with open(os.path.join(cat_dir, categories.slug(canon) + ".json"), "w") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        cat_index.append(
            {
                "slug": categories.slug(canon),
                "name": canon,
                "asset": categories.asset_class(canon),
                "count": len(rows),
            }
        )

    meta_payload = {
        "generated_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "as_of": dates[-1],
        "source": "AMFI (portal.amfiindia.com NAVAll.txt + DownloadNAVHistoryReport)",
        "windows": [{"key": k, "label": lbl, "days": d, "annualised": d >= 365}
                    for k, d, lbl in WINDOWS],
        "dates": dates,
        "rank_dates": dates[rank_offset:],
        "categories": cat_index,
    }
    with open(os.path.join(data_dir, "meta.json"), "w") as fh:
        json.dump(meta_payload, fh, separators=(",", ":"))

    published = {code for codes in by_cat.values() for code in codes}
    lookup = [[c, m["name"], categories.slug(m["category"]), m["plan"], m["amc"]]
              for c, m in schemes.items() if c in published]
    with open(os.path.join(data_dir, "lookup.json"), "w") as fh:
        json.dump(lookup, fh, separators=(",", ":"))

    return {
        "schemes": len(lookup),
        "dates": len(dates),
        "categories": len(cat_index),
        "as_of": dates[-1],
    }
