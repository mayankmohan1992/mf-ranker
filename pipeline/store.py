"""Local NAV store: SQLite, one row per scheme per date.

Scope decision (agreed): only **Growth** option schemes of **Direct** and
**Regular** plans are stored.  IDCW NAVs drop on every payout, so ranking them
by NAV return would be wrong; mixing plans in one rank list is also misleading.

The DB lives outside the deployed site and is what the `state` branch carries
between GitHub Actions runs.
"""
from __future__ import annotations

import datetime as dt
import gzip
import os
import shutil
import sqlite3

from . import amfi, categories

EPOCH = dt.date(1970, 1, 1)
STALE_MARGIN = 40   # days of slack so boundary schemes are not dropped by pack()

SCHEMA = """
CREATE TABLE IF NOT EXISTS nav (
    code TEXT NOT NULL,
    day  INTEGER NOT NULL,
    nav  REAL NOT NULL,
    PRIMARY KEY (code, day)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS schemes (
    code   TEXT PRIMARY KEY,
    name   TEXT,
    amc    TEXT,
    section TEXT,
    category TEXT,
    asset  TEXT,
    plan   TEXT,
    rgroup TEXT,
    first_day INTEGER,
    last_day  INTEGER
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS scheme_isin (
    code TEXT PRIMARY KEY,
    isin TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def to_day(d: dt.date) -> int:
    return (d - EPOCH).days


def from_day(n: int) -> dt.date:
    return EPOCH + dt.timedelta(days=int(n))


class Store:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")

    # -- writes ------------------------------------------------------------
    def ingest(self, rows) -> int:
        """Insert parsed AMFI rows. Returns number of Growth rows kept."""
        kept = 0
        nav_batch = []
        scheme_batch = []
        isin_batch = []
        cat_cache = {}
        for r in rows:
            if amfi.option_of(r) != "Growth":
                continue
            plan = amfi.plan_of(r)
            if plan not in ("Direct", "Regular"):
                continue
            section = r["section"] or ""
            if section not in cat_cache:
                canon = categories.canonical_category(section)
                cat_cache[section] = (canon, categories.asset_class(canon))
            canon, asset = cat_cache[section]
            code = r["code"]
            day = to_day(r["date"])
            if r.get("isin"):
                isin_batch.append((code, r["isin"]))
            nav_batch.append((code, day, r["nav"]))
            scheme_batch.append(
                (
                    code,
                    r["name"].strip(),
                    r["amc"].strip(),
                    section,
                    canon,
                    asset,
                    plan,
                    categories.rank_group(canon, r["name"]),
                    day,
                    day,
                )
            )
            kept += 1

        self.db.executemany(
            "INSERT INTO nav(code, day, nav) VALUES (?,?,?) "
            "ON CONFLICT(code, day) DO UPDATE SET nav=excluded.nav",
            nav_batch,
        )
        # scheme metadata: keep the longest name seen, latest amc/category
        self.db.executemany(
            """
            INSERT INTO schemes(code,name,amc,section,category,asset,plan,rgroup,first_day,last_day)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(code) DO UPDATE SET
                name = CASE WHEN length(excluded.name) > length(coalesce(schemes.name,''))
                            THEN excluded.name ELSE schemes.name END,
                amc = CASE WHEN coalesce(schemes.amc,'') = '' THEN excluded.amc ELSE schemes.amc END,
                section = excluded.section,
                category = excluded.category,
                asset = excluded.asset,
                plan = CASE WHEN coalesce(schemes.plan,'') = '' THEN excluded.plan ELSE schemes.plan END,
                rgroup = excluded.rgroup,
                first_day = min(coalesce(schemes.first_day, excluded.first_day), excluded.first_day),
                last_day = max(coalesce(schemes.last_day, excluded.last_day), excluded.last_day)
            """,
            scheme_batch,
        )
        if isin_batch:
            self.db.executemany(
                "INSERT INTO scheme_isin(code,isin) VALUES (?,?) "
                "ON CONFLICT(code) DO UPDATE SET isin = excluded.isin",
                isin_batch,
            )
        self.db.commit()
        return kept

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO meta(key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.db.commit()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        cur = self.db.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else default

    # -- reads -------------------------------------------------------------
    def max_day(self) -> int | None:
        cur = self.db.execute("SELECT max(day) FROM nav")
        row = cur.fetchone()
        return row[0] if row else None

    def scheme_count(self) -> int:
        return self.db.execute("SELECT count(*) FROM schemes").fetchone()[0]

    def nav_count(self) -> int:
        return self.db.execute("SELECT count(*) FROM nav").fetchone()[0]

    def schemes(self):
        cur = self.db.execute(
            "SELECT code,name,amc,category,asset,plan,rgroup,first_day,last_day FROM schemes"
        )
        for row in cur:
            yield {
                "code": row[0],
                "name": row[1],
                "amc": row[2],
                "category": row[3],
                "asset": row[4],
                "plan": row[5],
                "rgroup": row[6],
                "first_day": row[7],
                "last_day": row[8],
            }

    def isins(self):
        """code -> latest ISIN seen in AMFI files."""
        return dict(self.db.execute("SELECT code,isin FROM scheme_isin"))

    def series(self):
        """Yield (code, [ (day, nav), ... ]) ordered by date."""
        cur = self.db.execute("SELECT code, day, nav FROM nav ORDER BY code, day")
        code = None
        pts = []
        for c, d, n in cur:
            if c != code:
                if code is not None:
                    yield code, pts
                code, pts = c, []
            pts.append((d, n))
        if code is not None:
            yield code, pts

    def close(self):
        self.db.close()

    # -- state transfer ----------------------------------------------------
    def pack(self, out_path: str, keep_daily_days: int = 45, keep_years: float = 3.0) -> str:
        """Write a compact, single-file snapshot of the store for the `state` branch.

        The snapshot must be *lossless for the product*, not merely small. The
        product samples every series on a Friday grid with "as of" semantics
        (last NAV on or before the date), so for older history we keep exactly
        the row that sampler would pick for each Friday - including the Thursday
        before a market-holiday Friday. Any coarser rule (all Fridays, last row
        per week bin, ...) silently shifts every historical return.

        Rows newer than `keep_daily_days` are kept in full, and schemes with no
        NAV in the last `keep_years` are dropped: they are already excluded from
        publication and rank history only spans that window.

        1970-01-01 (day 0) was a Thursday, so day % 7 == 1 is a Friday.
        """
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.commit()

        end = self.db.execute("SELECT max(day) FROM nav").fetchone()[0]
        if end is None:
            raise RuntimeError("cannot pack an empty store")
        daily_cut = end - keep_daily_days
        # rank history spans compute.RANK_SERIES_WEEKS weeks and a sample may be
        # up to MAX_STALE days old, so keep schemes that contributed anywhere in it
        alive_cut = end - int(365.25 * keep_years) - STALE_MARGIN
        # every Friday, including ones inside the daily window: the row a Friday
        # resolves to may itself sit just below the daily cut-off
        fridays = [d for d in range(0, end + 1) if d % 7 == 1]

        work = out_path + ".db"
        if os.path.exists(work):
            os.remove(work)
        out = sqlite3.connect(work)
        out.executescript(SCHEMA)
        keep_schemes = [
            r for r in self.db.execute(
                "SELECT code,name,amc,section,category,asset,plan,rgroup,first_day,last_day "
                "FROM schemes WHERE coalesce(last_day,0) >= ?", (alive_cut,))
        ]
        alive = {r[0] for r in keep_schemes}
        out.executemany(
            "INSERT INTO schemes VALUES (?,?,?,?,?,?,?,?,?,?)", keep_schemes)
        out.executemany(
            "INSERT INTO scheme_isin VALUES (?,?)",
            self.db.execute("SELECT code,isin FROM scheme_isin"))

        batch = []
        code = None
        rows = []
        def flush(code, rows):
            if not alive.__contains__(code) or not rows:
                return
            days = [r[0] for r in rows]
            keep_idx = set()
            pos = 0
            for f in fridays:
                while pos < len(days) and days[pos] <= f:
                    pos += 1
                if pos:
                    keep_idx.add(pos - 1)          # last row on/before this Friday
            for i, (d, n) in enumerate(rows):
                if d >= daily_cut or i in keep_idx:
                    batch.append((code, d, n))

        for c, d, n in self.db.execute("SELECT code, day, nav FROM nav ORDER BY code, day"):
            if c != code:
                if code is not None:
                    flush(code, rows)
                code, rows = c, []
            rows.append((d, n))
            if len(batch) > 200000:
                out.executemany("INSERT INTO nav VALUES (?,?,?)", batch)
                batch.clear()
        flush(code, rows)
        if batch:
            out.executemany("INSERT INTO nav VALUES (?,?,?)", batch)
        out.executemany("INSERT INTO meta VALUES (?,?)",
                        self.db.execute("SELECT key,value FROM meta").fetchall())
        out.commit()
        out.execute("VACUUM")
        out.commit()
        out.close()

        tmp = out_path + ".tmp"
        with open(work, "rb") as src, gzip.open(tmp, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        os.replace(tmp, out_path)
        os.remove(work)
        return out_path


def unpack(state_gz: str, db_path: str) -> bool:
    """Restore a packed DB. Returns False when the archive is missing/invalid."""
    if not os.path.exists(state_gz):
        return False
    try:
        with gzip.open(state_gz, "rb") as src, open(db_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        with open(db_path, "rb") as fh:
            if fh.read(16) == b"":  # empty file guard
                return False
        return True
    except (OSError, EOFError, gzip.BadGzipFile):
        return False
