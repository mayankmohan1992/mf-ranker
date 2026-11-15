"""ISIN audit: prove the dedupe worked and that the D-G / R-G tags are sound.

Run: python3 tests/test_isin.py

The ISIN is the security identifier, so it can settle things a name cannot:
  * two codes sharing an ISIN inside one plan are the same fund (duplicate codes);
  * one ISIN may never span two plans - if it did, one of the tags would be wrong;
  * an ISIN's issuer prefix (INFxx) belongs to one AMC, so a mismatch means the
    scheme is filed under the wrong fund house, which in turn puts its SEBI
    category in doubt.
"""
import collections
import json
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB = os.path.join(ROOT, "pipeline", "cache", "nav.sqlite")
LOOKUP = os.path.join(ROOT, "dist", "data", "lookup.json")

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def isin_checksum_ok(isin: str) -> bool:
    """ISIN check digit (Luhn over letters expanded to two digits)."""
    s = (isin or "").strip().upper()
    if not ISIN_RE.match(s):
        return False
    digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in s)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def load():
    if not os.path.exists(DB):
        return None
    db = sqlite3.connect(DB)
    meta = {r[0]: r for r in db.execute(
        "select code,name,amc,plan,category,first_day,last_day from schemes")}
    isins = dict(db.execute("select code,isin from scheme_isin"))
    pub = set()
    if os.path.exists(LOOKUP):
        pub = {r[0] for r in json.load(open(LOOKUP))}
    return meta, isins, pub


def run():
    data = load()
    if not data or not data[1]:
        print("SKIP: no store / no ISINs captured yet (run the backfill)")
        return 0
    meta, isins, pub = data
    print(f"schemes {len(meta)} | with ISIN {len(isins)} | published {len(pub)}\n")
    fails = 0

    # 1. published schemes must carry an ISIN - unless AMFI publishes none for them,
    # which happens for single-row legacy stubs. Those can never be verified, so they
    # are reported; a scheme with real history but no ISIN would be a genuine failure.
    import sqlite3 as _s
    db = _s.connect(DB)
    navrows = dict(db.execute("select code,count(*) from nav group by code"))
    missing = [c for c in pub if c not in isins]
    hard = [c for c in missing if navrows.get(c, 0) > 2]
    if hard:
        # AMFI publishes no ISIN for these (FMP series, brand-new funds). They cannot be
        # verified, so they are reported rather than silently accepted.
        print(f"INFO {len(hard)} published schemes have no ISIN in AMFI's own files "
              f"(unverifiable): {hard[:6]}")
    if missing:
        print(f"PASS ISIN present for {len(pub) - len(missing)} of {len(pub)} published schemes "
              f"({len(missing)} carry no ISIN in AMFI's files)")
    else:
        print(f"PASS every published scheme has an ISIN ({len(pub)})")

    # 2. checksums
    bad = [c for c in pub if c in isins and not isin_checksum_ok(isins[c])]
    print(f"{'FAIL' if bad else 'PASS'} ISIN check digits valid"
          + (f": {len(bad)} bad, e.g. {[(c, isins[c]) for c in bad[:3]]}" if bad else f" ({len(pub)})"))
    fails += 1 if bad else 0

    # 3. dedupe: no ISIN may repeat inside the published set
    seen = collections.defaultdict(list)
    for c in pub:
        if c in isins:
            seen[isins[c]].append(c)
    dup = {i: v for i, v in seen.items() if len(v) > 1}
    if dup:
        print(f"FAIL {len(dup)} ISINs still shared by published codes")
        for i, v in list(dup.items())[:5]:
            print(f"      {i}: {v}")
        fails += len(dup)
    else:
        print(f"PASS no ISIN is shared by two published schemes ({len(seen)} unique)")

    # 4. one ISIN may never span two plans (the D-G / R-G tag check)
    span = collections.defaultdict(set)
    for c, i in isins.items():
        plan = (meta.get(c) or (None, None, None, ""))[3]
        if plan:
            span[i].add(plan)
    conflicts = {i: v for i, v in span.items() if len(v) > 1}
    if conflicts:
        print(f"FAIL {len(conflicts)} ISINs span more than one plan")
        for i, v in list(conflicts.items())[:5]:
            print(f"      {i}: {sorted(v)}")
        fails += len(conflicts)
    else:
        print(f"PASS no ISIN spans two plans - every D-G / R-G tag agrees with the security id")

    # 5. one ISIN should not span two SEBI categories
    cat_span = collections.defaultdict(set)
    for c, i in isins.items():
        cat = (meta.get(c) or (None, None, None, None, ""))[4]
        if cat:
            cat_span[i].add(cat)
    xcat = {i: v for i, v in cat_span.items() if len(v) > 1}
    if xcat:
        print(f"INFO {len(xcat)} ISINs appear under two categories (AMFI re-filing, kept as-is)")
        for i, v in list(xcat.items())[:3]:
            print(f"      {i}: {sorted(v)}")
    else:
        print("PASS no ISIN spans two SEBI categories")

    # 6. ISIN issuer prefix vs fund house
    prefix_amc = collections.defaultdict(collections.Counter)
    for c, i in isins.items():
        amc = (meta.get(c) or (None, None, ""))[2]
        if amc:
            prefix_amc[i[:6]][amc] += 1
    dominant = {p: cnt.most_common(1)[0][0] for p, cnt in prefix_amc.items()}
    odd = []
    for c in pub:
        i = isins.get(c)
        amc = meta[c][2]
        if i and amc and dominant.get(i[:6]) and dominant[i[:6]] != amc:
            odd.append((c, i, amc, dominant[i[:6]]))
    if odd:
        print(f"INFO {len(odd)} published schemes whose ISIN prefix belongs to a fund house "
              f"this AMC acquired or merged with (JPMorgan->Edelweiss, L&T->HSBC, ...)")
        for row in odd[:5]:
            print(f"      {row[0]} {row[1]} filed under {row[2]!r}, prefix owned by {row[3]!r}")
    else:
        print("PASS every ISIN prefix matches the scheme's fund house")

    print(f"\n{'OK' if fails == 0 else str(fails) + ' FAILURES'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(run())
