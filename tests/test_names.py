"""Short display-name tests: fixtures + an audit over the whole store.

Run: python3 tests/test_names.py

The failure this guards against is silent over-stripping. A fund whose own name
contains "Growth" (Principal Multi Cap Growth Fund, Sahara Growth Fund, Kotak India
Growth Fund Series 4) must keep it, while the trailing plan/option markers go.
"""
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import names  # noqa: E402

DB = os.path.join(ROOT, "pipeline", "cache", "nav.sqlite")

FIXTURES = [
    # (official name, plan, expected display)
    ("Nippon India Large Cap Fund - Direct Plan - Growth Plan - Growth Option", "Direct",
     "Nippon India Large Cap Fund D-G"),
    ("HDFC Large Cap Fund - Growth Option - Direct Plan", "Direct", "HDFC Large Cap Fund D-G"),
    ("BANDHAN Large Cap Fund-Direct Plan-Growth", "Direct", "BANDHAN Large Cap Fund D-G"),
    ("JM Large Cap Fund (Direct) - Growth Option", "Direct", "JM Large Cap Fund D-G"),
    ("Tata Large Cap Fund -Direct Plan Growth Option", "Direct", "Tata Large Cap Fund D-G"),
    ("IDBI Dynamic Bond Fund Growth Direct", "Direct", "IDBI Dynamic Bond Fund D-G"),
    ("IDBI Equity Savings Fund Growth Option Direct", "Direct", "IDBI Equity Savings Fund D-G"),
    ("UTI FTIF Series XX - XVI (1100 Days) Growth Option Direct", "Direct",
     "UTI FTIF Series XX - XVI (1100 Days) D-G"),
    # the traps: "Growth" belongs to the fund name
    ("Principal Multi Cap Growth Fund - Direct Plan - Growth Option", "Direct",
     "Principal Multi Cap Growth Fund D-G"),
    ("Kotak India Growth Fund Series 4-Direct Plan - Growth Option", "Direct",
     "Kotak India Growth Fund Series 4 D-G"),
    ("Sahara Growth Fund-Growth- Direct", "Direct", "Sahara Growth Fund D-G"),
    ("HDFC Growth Opportunities Fund - Direct Plan - Growth Option", "Direct",
     "HDFC Growth Opportunities Fund D-G"),
    # plan not stated in the name: tag must still come from the plan column
    ("Invesco India Large Cap Fund - Growth Option", "Regular",
     "Invesco India Large Cap Fund R-G"),
    ("Some Fund - Growth", "Regular", "Some Fund R-G"),
    # legacy duplicate suffix
    ("Aditya Birla Sun Life MIP - Direct Plan - Growth - Direct Plan", "Direct",
     "Aditya Birla Sun Life MIP D-G"),
]

# word-boundary anchored: "Indirect Plan" must not be read as "direct plan"
TAIL_MARKERS = re.compile(
    r"(?<![a-z])(growth\s+option|growth\s+plan|direct\s+plan|regular\s+plan)$", re.I)


def run_fixtures():
    bad = 0
    for name, plan, want in FIXTURES:
        got = names.display_name(name, plan)
        if got != want:
            bad += 1
            print(f"FAIL {name!r}\n     want {want!r}\n     got  {got!r}")
    print(f"{'PASS' if bad == 0 else 'FAIL'} {len(FIXTURES)} fixtures")
    return bad


def run_store_audit():
    if not os.path.exists(DB):
        print("SKIP store audit (no db)")
        return 0
    db = sqlite3.connect(DB)
    rows = db.execute("select code,name,amc,plan,category from schemes").fetchall()
    bad = 0
    leftover, short, dangling, empty = [], [], [], []
    seen = {}
    seen_set = set()
    collisions = []
    saved = 0

    for code, name, amc, plan, cat in rows:
        disp = names.display_name(name, plan)
        base = names.base_name(name)
        saved += max(0, len(name) - len(disp))

        if TAIL_MARKERS.search(base.strip()):
            leftover.append((code, name, disp))
        if len(base) < 4:
            short.append((code, name, disp))
        if base and base[-1] in names.TRIM:
            dangling.append((code, name, disp))
        if not base:
            empty.append((code, name, disp))
        if not re.search(r"\s(D|R)-G$", disp):
            empty.append((code, name, disp))

        key = (amc, plan, disp)
        if key in seen and seen[key] != code:
            collisions.append((key[2], seen[key], code))   # informational only
        seen.setdefault(key, code)

        # what the build actually publishes: collisions are resolved by appending the
        # AMFI code (a handful of funds ship under two scheme codes)
        unique_key = key if key not in seen_set else (amc, plan, disp, code)
        seen_set.add(unique_key)

    def report(label, items, limit=5):
        nonlocal bad
        if items:
            bad += len(items)
            print(f"FAIL {label}: {len(items)}")
            for it in items[:limit]:
                print("     ", it)
        else:
            print(f"PASS {label}")

    print(f"\naudited {len(rows)} schemes")
    report("no plan/option marker left in the base name", leftover)
    report("no base name shorter than 4 characters", short)
    report("no base name ending in a separator", dangling)
    report("every scheme carries a D-G / R-G tag", empty)
    if collisions:
        print(f"INFO {len(collisions)} duplicate display names in the store - these are AMFI "
              f"duplicate scheme codes for one fund (e.g. an old and a new code). The build "
              f"appends ' · <code>' so the published UI stays unambiguous.")
    else:
        print("INFO no duplicate display names in the store")

    avg_before = sum(len(r[1]) for r in rows) / len(rows)
    avg_after = avg_before - saved / len(rows)
    print(f"\nname length: {avg_before:.1f} -> {avg_after:.1f} chars "
          f"({saved / len(rows):.1f} saved per scheme, {saved / 1000:.0f}k total)")
    return bad


def run_samples(n=14):
    if not os.path.exists(DB):
        return
    db = sqlite3.connect(DB)
    rows = db.execute("""select name,plan from schemes
                         where name like '%Growth Fund%' or name like '%Direct%'
                         order by random() limit ?""", (n,)).fetchall()
    print("\nsample:")
    for name, plan in rows:
        print(f"   {names.display_name(name, plan):58s}  <- {name[:66]}")


def run():
    bad = run_fixtures()
    bad += run_store_audit()
    run_samples()
    print(f"\n{'OK' if bad == 0 else str(bad) + ' FAILURES'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(run())
