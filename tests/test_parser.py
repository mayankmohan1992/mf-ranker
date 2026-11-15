"""Parser regression tests.

Run: python3 tests/test_parser.py

The layout-detection bug these guard against: AMFI's history files put the scheme
name in field 2 and the NAVAll files put an ISIN there. Detecting the layout with
`field2.startswith("IN")` silently mis-parsed every scheme whose *name* starts with
"In" (the whole Invesco range, 247 scheme codes) and dropped its history.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import amfi, categories  # noqa: E402

CASES = [
    (
        "history layout, fund name starts with IN (the regression)",
        "Open Ended Schemes ( Equity Scheme - Large Cap Fund )\n"
        "Invesco Mutual Fund\n"
        "120392;Invesco India Large Cap Fund - Direct Plan - Growth;Direct Plan;Growth;INF205K01LB0;;83.02;01-Oct-2026",
        {"code": "120392", "name": "Invesco India Large Cap Fund - Direct Plan - Growth",
         "plan": "Direct", "option": "Growth", "nav": 83.02},
    ),
    (
        "NAVAll layout (ISIN then name)",
        "Open Ended Schemes(Equity Scheme - Large Cap Fund)\n"
        "Axis Mutual Fund\n"
        "135762;INF846K01WO1;-;Axis Children's Fund;Direct Plan;Growth Option;31.0814;13-Nov-2026",
        {"code": "135762", "name": "Axis Children's Fund", "plan": "Direct",
         "option": "Growth Option", "nav": 31.0814},
    ),
    (
        "history layout, blank plan/option/ISIN columns",
        "Open Ended Schemes ( Money Market )\n"
        "Taurus Mutual Fund\n"
        "139619;Taurus Investor Education Pool - Unclaimed Dividend - Growth;;;;;10.0000;01-Oct-2026",
        {"code": "139619",
         "name": "Taurus Investor Education Pool - Unclaimed Dividend - Growth",
         "plan": "", "option": "", "nav": 10.0},
    ),
    (
        "NAVAll layout with missing ISINs",
        "Open Ended Schemes(Debt Scheme - Liquid Fund)\n"
        "X Mutual Fund\n"
        "999999;;;Some Liquid Fund;Regular Plan;Growth Option;10.5000;13-Nov-2026",
        {"code": "999999", "name": "Some Liquid Fund", "plan": "Regular",
         "option": "Growth Option", "nav": 10.5},
    ),
]


def run():
    failures = 0
    for label, text, expected in CASES:
        rows = list(amfi.parse(text))
        if len(rows) != 1:
            print(f"FAIL {label}: expected 1 row, got {len(rows)}")
            failures += 1
            continue
        row = rows[0]
        bad = [k for k, v in expected.items() if row.get(k) != v]
        if bad:
            print(f"FAIL {label}: {bad} -> {({k: row.get(k) for k in bad})}")
            failures += 1
        else:
            print(f"PASS {label}")

    # plan/option classification must survive the layout handling
    row = list(amfi.parse(CASES[0][1]))[0]
    if (amfi.plan_of(row), amfi.option_of(row)) != ("Direct", "Growth"):
        print("FAIL plan/option classification")
        failures += 1
    else:
        print("PASS plan/option classification")

    # every AMFI section label we have seen must land in a real category
    if categories.canonical_category("Equity Schemes - Large Cap Fund") != "Large Cap Fund":
        print("FAIL category canonicalisation")
        failures += 1
    else:
        print("PASS category canonicalisation")

    print(f"\n{'OK' if failures == 0 else str(failures) + ' FAILURES'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
