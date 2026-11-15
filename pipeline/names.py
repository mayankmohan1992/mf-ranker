"""Display names: "Fund - Direct Plan - Growth Option" -> "Fund D-G".

Rules that keep this safe:

* The official AMFI name is never modified - the short form is a derived field.
* Markers are stripped only from the **tail**, only after a separator, and only a
  bounded number of times. "Principal Multi Cap Growth Fund - Direct Plan - Growth
  Option" keeps its own "Growth" because after the suffixes are removed the string
  ends in "Fund", and "growth" is allowed to be stripped only once.
* The plan tag comes from the parsed plan column, not from the string, so a scheme
  whose name omits its plan still gets the right tag.
"""
import re

# separators allowed immediately BEFORE a marker (en/em dashes, NBSP, brackets)
SEP = " \t\u00a0-–—()[].,:;/\\*_"
# separators trimmed off the RESULT. Brackets are deliberately excluded: "(1100 Days)"
# is part of the fund's name, and trimming it produced "Kotak FMP Series 131 (1061 Days".
TRIM = " \t\u00a0-–—.,:;/\\*_"

GROWTH = ("growth option", "growth plan", "growth")
DIST = (
    "income distribution cum capital withdrawal",
    "payout of income distribution",
    "reinvestment of income distribution",
    "half yearly income distribution",
    "quarterly income distribution",
    "monthly income distribution",
    "income distribution",
    "dividend option",
    "dividend payout",
    "dividend",
    "idcw option",
    "idcw",
    "bonus option",
    "bonus",
)
PLAN = ("direct plan", "direct", "regular plan", "regular")

TAG = {"Direct": "D-G", "Regular": "R-G"}

MAX_PLAN = 2      # "Direct Plan - Growth Option - Direct Plan" exists in legacy data
MAX_GROWTH = 2    # "...-Growth Plan-Growth Option" is one scheme with two growth words
MAX_DIST = 2


def _rstrip_sep(s: str) -> str:
    return s.rstrip(TRIM)


def _cut_tail(s: str, tokens, depth: int = 0):
    """Return s with one trailing token (plus its separator) removed, or None."""
    base = _rstrip_sep(s)
    closing = ""
    if depth < 2 and base and base[-1] in ")]":
        closing = base[-1]
        base = _rstrip_sep(base[:-1])
    low = base.lower()
    for tok in tokens:
        if low.endswith(tok):
            cut = len(base) - len(tok)
            if cut <= 0:
                continue                      # never strip the whole name
            if base[cut - 1] in SEP:
                return _rstrip_sep(base[:cut]) + closing
    if closing:
        return _cut_tail(base, tokens, depth + 1) + closing if _cut_tail(base, tokens, depth + 1) else None
    return None


# "(Direct)", "[Regular Plan]" - the plan is bracketed mid-string, not a tail marker
_BRACKETED_PLAN = re.compile(
    r"[\[({]\s*(?:(?:direct|regular)(?:\s+plan)?|growth(?:\s+option)?)\s*[\])}]", re.I)


def base_name(name: str) -> str:
    """Official name minus plan/option markers."""
    s = " ".join((name or "").split())        # collapse NBSP / double spaces
    s = _rstrip_sep(_BRACKETED_PLAN.sub(" ", s))
    used = {"plan": 0, "growth": 0, "dist": 0}
    for _ in range(10):
        n = _cut_tail(s, PLAN)
        if n is not None and used["plan"] < MAX_PLAN:
            used["plan"] += 1
            s = n
            continue
        n = _cut_tail(s, GROWTH)
        if n is not None and used["growth"] < MAX_GROWTH:
            used["growth"] += 1
            s = n
            continue
        n = _cut_tail(s, DIST)
        if n is not None and used["dist"] < MAX_DIST:
            used["dist"] += 1
            s = n
            continue
        break
    return s


def display_name(name: str, plan: str) -> str:
    """Short display name, e.g. 'Nippon India Large Cap Fund D-G'."""
    b = base_name(name)
    tag = TAG.get(plan)
    if not b or not tag:
        return name
    return f"{b} {tag}"
