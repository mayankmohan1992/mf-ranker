"""AMFI data access.

Only official AMFI endpoints are used. No third-party NAV sources.

  * https://portal.amfiindia.com/spages/NAVAll.txt            -> every scheme's latest NAV (one file, ~1.5 MB)
  * https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx?frmdt=&todt=
                                                              -> all schemes, all dates in range (~24 MB/month)

Both files share a shape: semicolon rows, with "Open Ended Schemes(<category>)" /
"Close Ended Schemes(<category>)" section headers and bare AMC-name lines in between.
The category therefore comes from AMFI itself, not from guessing at fund names.
"""
from __future__ import annotations

import datetime as dt
import re
import time
import urllib.error
import urllib.request

NAVALL_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
HIST_URL = (
    "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx"
    "?frmdt={frm}&todt={to}"
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

SECTION_RE = re.compile(r"^(Open|Close)\s*Ended\s*Schemes", re.I)

# Indian ISIN: "IN" + 10 alphanumerics. Used to tell the two 8-column layouts apart.
# A plain startswith("IN") test is wrong: scheme names do it too - "Invesco India
# Large Cap Fund" was read as an ISIN and every Invesco row in the history files
# was dropped as unparseable.
ISIN_RE = re.compile(r"^IN[A-Z0-9]{10}$")
PLAN_WORDS = ("direct", "regular")
OPTION_WORDS = ("growth", "idcw", "dividend", "bonus", "payout", "reinvest")


def _is_isin(text: str) -> bool:
    return bool(ISIN_RE.match((text or "").strip().upper()))


def _looks_plan(text: str) -> bool:
    return (text or "").strip().lower().startswith(PLAN_WORDS)


def _looks_option(text: str) -> bool:
    low = (text or "").lower()
    return any(w in low for w in OPTION_WORDS)


def _layout8(parts):
    """Decide between the two 8-column layouts by scoring both readings.

      NAVAll : code;isin1;isin2;name;plan;option;nav;date
      history: code;name;plan;option;isin1;isin2;nav;date
    """
    navall = (_looks_plan(parts[4]) + _looks_option(parts[5])
              + _is_isin(parts[1]) + _is_isin(parts[2]))
    hist = (_looks_plan(parts[2]) + _looks_option(parts[3])
            + _is_isin(parts[4]) + _is_isin(parts[5]))
    return "navall" if navall > hist else "history"
DATE_RE = re.compile(r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})$")


def fetch(url: str, retries: int = 4, timeout: int = 300) -> str:
    """GET a URL as text, with backoff. AMFI occasionally returns an ASP.NET error page."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            text = raw.decode("utf-8", errors="ignore")
            if "Scheme Code" not in text:
                raise ValueError("no scheme header in response (likely an error page)")
            return text
        except (urllib.error.URLError, ValueError, OSError, TimeoutError) as exc:
            last = exc
            time.sleep(2 + 3 * attempt)
    raise RuntimeError(f"AMFI fetch failed after {retries} tries: {url} :: {last}")


def fetch_navall() -> str:
    return fetch(NAVALL_URL)


def fetch_history(frm: dt.date, to: dt.date) -> str:
    url = HIST_URL.format(frm=frm.strftime("%d-%b-%Y"), to=to.strftime("%d-%b-%Y"))
    return fetch(url)


def parse_date(text: str) -> dt.date | None:
    m = DATE_RE.match(text.strip())
    if not m:
        return None
    d, mon, y = m.groups()
    month = MONTHS.get(mon.lower())
    if not month:
        return None
    try:
        return dt.date(int(y), month, int(d))
    except ValueError:
        return None


def _section_category(line: str) -> str | None:
    """'Open Ended Schemes(Equity Schemes - Large Cap Fund)' -> 'Equity Schemes - Large Cap Fund'"""
    if not SECTION_RE.match(line):
        return None
    start = line.find("(")
    if start == -1:
        rest = SECTION_RE.sub("", line)
        return rest.strip() or None
    inner = line[start + 1:]
    if inner.endswith(")"):
        inner = inner[:-1]
    return inner.strip() or None


def parse(text: str):
    """Yield row dicts. Handles both the current 8-column layout and the older 6-column one.

    New layout (both files today):  code;isin1;isin2;name;plan;option;nav;date        (NAVAll)
                                    code;name;plan;option;isin1;isin2;nav;date        (history)
    Old layout:                     code;<isin or name>;...;nav;date
    Rule: if field[1] starts with 'IN' it is an ISIN and the name sits at index 3,
    otherwise the name is at index 1. NAV/date are always the last two fields.
    """
    section = ""
    scheme_type = ""
    amc = ""
    for raw in text.splitlines():
        line = raw.strip().strip("\r")
        if not line or line.lower().startswith("scheme code"):
            continue
        if ";" not in line:
            sec = _section_category(line)
            if sec is not None:
                inner = sec.lower()
                scheme_type = "Close" if line.lower().startswith("close") else "Open"
                section = sec
                amc = ""
            else:
                amc = line
            continue

        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 5:
            continue
        nav_text, date_text = parts[-2], parts[-1]
        date = parse_date(date_text)
        if date is None:
            continue
        try:
            nav = float(nav_text)
        except ValueError:
            continue
        if nav <= 0:
            continue

        code = parts[0]
        if not code.isdigit():
            continue

        if len(parts) >= 8:
            if _layout8(parts) == "navall":
                name, middle = parts[3], parts[4:-2]
            else:
                name, middle = parts[1], parts[2:-2]
        else:
            # legacy 6-column files: name sits at [1] unless [1] is an ISIN
            if len(parts) > 3 and _is_isin(parts[1]):
                name, middle = parts[3], parts[4:-2]
            else:
                name, middle = parts[1], parts[2:-2]

        plan = ""
        option = ""
        isin = ""
        for field in middle:
            low = field.lower()
            if ISIN_RE.match(field.upper()):      # strict shape, not a prefix guess
                if not isin:
                    isin = field.upper()
                continue
            if not plan and ("direct" in low or "regular" in low):
                plan = "Direct" if "direct" in low else "Regular"
            elif not option and any(
                k in low for k in ("growth", "idcw", "dividend", "bonus", "payout", "reinvest")
            ):
                option = field

        yield {
            "code": code,
            "name": name,
            "plan": plan,
            "option": option,
            "isin": isin,
            "nav": nav,
            "date": date,
            "section": section,
            "scheme_type": scheme_type,
            "amc": amc,
        }


def plan_of(row) -> str:
    p = (row.get("plan") or "").lower()
    if "direct" in p:
        return "Direct"
    if "regular" in p:
        return "Regular"
    n = (row.get("name") or "").lower()
    if "direct" in n:
        return "Direct"
    if "regular" in n:
        return "Regular"
    return "Unspecified"


def option_of(row) -> str:
    o = (row.get("option") or "").lower()
    n = (row.get("name") or "").lower()
    blob = o + " " + n
    if "idcw" in blob or "dividend" in blob or "bonus" in blob:
        return "IDCW"
    if "growth" in blob:
        return "Growth"
    return "Other"


def month_spans(start: dt.date, end: dt.date):
    """Split [start, end] into month-sized (first, last) date pairs, inclusive."""
    cur = dt.date(start.year, start.month, 1)
    while cur <= end:
        if cur.month == 12:
            nxt = dt.date(cur.year + 1, 1, 1)
        else:
            nxt = dt.date(cur.year, cur.month + 1, 1)
        lo = max(cur, start)
        hi = min(nxt - dt.timedelta(days=1), end)
        if lo <= hi:
            yield lo, hi
        cur = nxt
