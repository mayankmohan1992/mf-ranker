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
import statistics
import re
import shutil

from . import categories
from . import sip as sipmod
from . import names as namemod

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

# The ranking basis is the observation frequency of the rank series. The table
# shows the rank as of the last COMPLETED bucket of the selected basis, so
# "weekly" and "quarterly" are genuinely different numbers, not the same one
# relabelled.
BASES = [
    ("weekly", "Weekly"),
    ("monthly", "Monthly"),
    ("quarterly", "Quarterly"),
    ("halfyearly", "Half-yearly"),
    ("annual", "Annual"),
]


def bucket_of(day: int, basis: str):
    d = dt.date(1970, 1, 1) + dt.timedelta(days=day)
    if basis == "weekly":
        iso = d.isocalendar()
        return (iso[0], iso[1])
    if basis == "monthly":
        return (d.year, d.month)
    if basis == "quarterly":
        return (d.year, (d.month - 1) // 3)
    if basis == "halfyearly":
        return (d.year, 0 if d.month <= 6 else 1)
    return (d.year,)


def last_completed_index(days, basis: str) -> int:
    """Index of the last observation in the most recent *finished* bucket."""
    cur = bucket_of(days[-1], basis)
    for i in range(len(days) - 1, -1, -1):
        if bucket_of(days[i], basis) != cur:
            return i
    return len(days) - 1


def prev_bucket_index(days, i: int, basis: str) -> int:
    """Index of the last observation of the bucket before the one holding i."""
    cur = bucket_of(days[i], basis)
    for j in range(i - 1, -1, -1):
        if bucket_of(days[j], basis) != cur:
            return j
    return -1
NAV_SERIES_WEEKS = 522   # ~10 years of weekly NAV points for the NAV chart
RANK_SERIES_WEEKS = 156  # ~3 years of weekly rank points for the rank chart
SAMPLE_TOLERANCE = 12
ACTIVE_DAYS = 45    # days a weekly sample may drift from the exact Friday
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


def _sip_medians(rows, sip_data):
    """Median SIP XIRR per (plan, tenure, day) so the UI can rank a fund without
    fetching every peer's series."""
    out = {}
    for plan in ("Direct", "Regular"):
        cells = [[[] for _ in sipmod.DAYS] for _ in sipmod.STARTS]
        any_data = False
        for row in rows:
            if row["p"] != plan:
                continue
            d = sip_data.get(row["c"])
            if not d:
                continue
            for si in range(len(sipmod.STARTS)):
                for di in range(len(sipmod.DAYS)):
                    v = d["x"][si][di]
                    if v is not None:
                        cells[si][di].append(v)
                        any_data = True
        if not any_data:
            continue
        grid = []
        for si in range(len(sipmod.STARTS)):
            grow = []
            for di in range(len(sipmod.DAYS)):
                vals = sorted(cells[si][di])
                grow.append(None if not vals else int(round(statistics.median(vals))))
            grid.append(grow)
        out[plan] = grid
    return out


# "Unclaimed Redemption Plan" / "Unclaimed Brokerage I.E.F." are AMFI's parking
# schemes for unclaimed amounts, not retail schemes: AMFI publishes no ISIN for them,
# their NAVs are not comparable, and they diluted the peer groups.
NOT_A_RETAIL_SCHEME = re.compile(r"unclaimed|i\.e\.f|brokerage|unit linked insurance", re.I)


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
    sip_data = {}
    cy_data = {}
    for code, pts in store.series():
        if code not in schemes:
            continue
        series[code] = _sample(pts, nav_grid)
        # SIP / calendar years come from the FULL daily series, not the weekly grid:
        # an instalment must buy at the NAV actually published on that date.
        meta_s = schemes[code]
        if meta_s["last_day"] is not None and meta_s["last_day"] >= end_day - ACTIVE_DAYS:
            plan = sipmod.plan(pts, end_day)
            if plan is not None:
                sip_data[code] = plan
                cy_data[code] = sipmod.calendar_years(pts, end_day)

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
    # totals are per group, per window, per observation - not a single scalar,
    # otherwise "3/38" lies as soon as you look at anything but the last week
    group_tot = {}
    group_of = {}

    for key, codes in groups.items():
        for code in codes:
            group_of[code] = key
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
                group_tot.setdefault((key, wk), [None] * len(rank_grid))[ri] = total
                for pos, (_, code) in enumerate(pairs, start=1):
                    ranks[code][wk][ri] = pos

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
    by_cat = {}
    for code, meta in schemes.items():
        if code not in rets:
            continue
        if meta["last_day"] is None or meta["last_day"] < end_day - ACTIVE_DAYS:
            continue
        if NOT_A_RETAIL_SCHEME.search(meta["name"] or ""):
            continue
        by_cat.setdefault(meta["category"], []).append(code)

    # ---- ISIN dedupe --------------------------------------------------------
    # AMFI ships a few funds under two scheme codes. The ISIN is the security id, so
    # two codes with the same ISIN in the same plan are the same fund: keep the one
    # with the live, longer series and drop the rest from publication (they stay in
    # the store, so history is not lost).
    isins = store.isins()
    published_codes = [c for codes in by_cat.values() for c in codes]
    _by_isin = {}
    for c in published_codes:
        i = isins.get(c)
        if i:
            _by_isin.setdefault((i, schemes[c]["plan"]), []).append(c)
    dropped = {}
    for (_i, _p), codes in _by_isin.items():
        if len(codes) < 2:
            continue

        def _score(c):
            m = schemes[c]
            alive = 1 if (m["last_day"] or 0) >= end_day - ACTIVE_DAYS else 0
            return (alive, (m["last_day"] or 0) - (m["first_day"] or 0), c)

        keep = max(codes, key=_score)
        for c in codes:
            if c != keep:
                dropped[c] = keep
    if dropped:
        for canon in list(by_cat):
            kept_codes = [c for c in by_cat[canon] if c not in dropped]
            if kept_codes:
                by_cat[canon] = kept_codes
            else:
                del by_cat[canon]
        published_codes = [c for c in published_codes if c not in dropped]

    # ---- short display names ------------------------------------------------
    # "Fund - Direct Plan - Growth Option" -> "Fund D-G". The official name is kept
    # in "n"; this is a derived field. AMFI ships a handful of duplicate codes for the
    # same fund, which collapse to one display name, so those get the code appended.
    published_codes = [c for codes in by_cat.values() for c in codes]
    disp = {c: namemod.display_name(schemes[c]["name"], schemes[c]["plan"]) for c in published_codes}
    _by_disp = {}
    for c in published_codes:
        _by_disp.setdefault((schemes[c]["amc"], schemes[c]["plan"], disp[c]), []).append(c)
    dup_display = 0
    for key, codes in _by_disp.items():
        if len(codes) > 1:
            dup_display += len(codes)
            for c in codes:
                disp[c] = f"{disp[c]} · {c}"

    def enc_rank(v):
        return 0 if v is None else v          # 0 is never a valid rank -> cheap null

    cat_index = []
    latest_i = len(nav_grid) - 1

    # where each basis reads its rank from: the last finished week / month / quarter / ...
    basis_idx = {b: last_completed_index(rank_grid, b) for b, _ in BASES}
    basis_prev = {b: prev_bucket_index(rank_grid, basis_idx[b], b) for b, _ in BASES}

    for canon in sorted(by_cat, key=lambda c: (categories.order_of(c), c)):
        codes = by_cat[canon]
        rows = []
        for code in sorted(codes, key=lambda c: schemes[c]["name"]):
            meta = schemes[code]
            gkey = group_of.get(code)
            ret_map = {key: rets[code][key][latest_i] for key, _, _ in WINDOWS}
            # Per-basis values are POSITIONAL arrays in BASES order (meta.bases gives
            # the order). Keyed objects repeated "weekly"/"monthly"/... once per value
            # and inflated the biggest category file to 1.5 MB.
            k_map, n_map, d_map = {}, {}, {}
            for key, _, _ in WINDOWS:
                hist = ranks[code][key]
                tot = group_tot.get((gkey, key)) or []
                kb, nb, db = [], [], []
                for b, _ in BASES:
                    i = basis_idx[b]
                    r = hist[i] if 0 <= i < len(hist) else None
                    kb.append(r)
                    nb.append(tot[i] if (r is not None and i < len(tot)) else None)
                    j = basis_prev[b]
                    r_prev = hist[j] if 0 <= j < len(hist) else None
                    db.append(None if (r is None or r_prev is None) else r_prev - r)
                k_map[key], n_map[key], d_map[key] = kb, nb, db

            # per-scheme series file: NAV history + rank history, fetched on click
            navs = series[code]
            payload = {
                "c": code,
                "v": [0 if v is None else round(v, 4) for v in navs],
                "h": {k: [enc_rank(x) for x in ranks[code][k]] for k, _, _ in WINDOWS},
                "sip": sip_data.get(code),
                "cy": cy_data.get(code) or {},
            }
            with open(os.path.join(ser_dir, code + ".json"), "w") as fh:
                json.dump(payload, fh, separators=(",", ":"))

            rows.append(
                {
                    "c": code,
                    "n": meta["name"],          # official AMFI name
                    "dn": disp[code],          # short display name ("... D-G")
                    "a": meta["amc"],
                    "p": meta["plan"],
                    "g": meta["rgroup"] or "",
                    "r": ret_map,
                    "k": k_map,
                    "N": n_map,
                    "d": d_map,
                }
            )
        payload = {
            "name": canon,
            "asset": categories.asset_class(canon),
            "count": len(rows),
            "schemes": rows,
            "sipm": _sip_medians(rows, sip_data),
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
        "bases": [{"key": b, "label": lbl} for b, lbl in BASES],
        "basis_asof": {b: dates[rank_offset + basis_idx[b]] for b, _ in BASES},
        "basis_prev_asof": {b: (dates[rank_offset + basis_prev[b]] if basis_prev[b] >= 0 else None)
                            for b, _ in BASES},
        "categories": cat_index,
        "sip": {
            "starts": sipmod.STARTS,
            "days": sipmod.DAYS,
            "amount": 1000,
            "min_instalments": sipmod.MIN_INSTALMENTS,
            "note": "XIRR per tenure x SIP day, instalments at the first NAV on/after "
                    "the chosen day, growth option only, no exit load or tax",
        },
    }
    with open(os.path.join(data_dir, "meta.json"), "w") as fh:
        json.dump(meta_payload, fh, separators=(",", ":"))

    published = {code for codes in by_cat.values() for code in codes}
    lookup = [[c, m["name"], categories.slug(m["category"]), m["plan"], m["amc"], disp.get(c, m["name"])]
              for c, m in schemes.items() if c in published]
    with open(os.path.join(data_dir, "lookup.json"), "w") as fh:
        json.dump(lookup, fh, separators=(",", ":"))

    return {
        "schemes": len(lookup),
        "isin_duplicates_dropped": len(dropped),
        "duplicate_display_names": dup_display,
        "dates": len(dates),
        "categories": len(cat_index),
        "as_of": dates[-1],
    }
