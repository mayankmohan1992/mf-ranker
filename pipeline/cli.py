"""Pipeline entry points.

  python -m pipeline.cli backfill --years 10   # one-time / self-healing full history
  python -m pipeline.cli daily                 # today's NAVAll into the store
  python -m pipeline.cli build                 # store -> dist/ (static site)
  python -m pipeline.cli state-unpack          # restore DB from state branch archive
  python -m pipeline.cli state-pack            # archive DB for state branch
  python -m pipeline.cli all                   # backfill if needed + daily + build
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import datetime as dt
import gzip
import os
import sys
import time

from . import amfi, categories, compute
from .store import Store, unpack

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "pipeline", "cache")
RAW = os.path.join(CACHE, "raw")
DB = os.path.join(CACHE, "nav.sqlite")
STATE = os.path.join(CACHE, "state.sqlite.gz")
DIST = os.path.join(ROOT, "dist")


def _raw_path(lo: dt.date) -> str:
    return os.path.join(RAW, lo.strftime("%Y-%m") + ".txt.gz")


def _load_span(lo: dt.date, hi: dt.date, workers_ref=None) -> str:
    path = _raw_path(lo)
    if os.path.exists(path):
        with gzip.open(path, "rt", errors="ignore") as fh:
            return fh.read()
    text = amfi.fetch_history(lo, hi)
    os.makedirs(RAW, exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", compresslevel=6) as fh:
        fh.write(text)
    os.replace(tmp, path)
    return text


def backfill(years: float = 10.0, workers: int = 6, quiet: bool = False) -> None:
    end = dt.date.today()
    start = end - dt.timedelta(days=int(365.25 * years))
    spans = list(amfi.month_spans(start, end))
    t0 = time.time()
    print(f"backfill: {len(spans)} month chunks {spans[0][0]} .. {spans[-1][1]}", flush=True)
    st = Store(DB)
    done = 0

    def work(span):
        lo, hi = span
        return lo, _load_span(lo, hi)

    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for lo, text in pool.map(work, spans):
            kept = st.ingest(amfi.parse(text))
            done += 1
            if not quiet and (done % 5 == 0 or done == len(spans)):
                print(
                    f"  [{done}/{len(spans)}] {lo:%Y-%m} rows_kept={kept} "
                    f"schemes={st.scheme_count()} navs={st.nav_count()} "
                    f"{time.time()-t0:.0f}s",
                    flush=True,
                )
    st.set_meta("backfill_done", dt.datetime.now().isoformat(timespec="seconds"))
    st.set_meta("backfill_start", start.isoformat())
    st.close()
    print(f"backfill complete in {time.time()-t0:.0f}s", flush=True)


def daily() -> None:
    st = Store(DB)
    before = st.nav_count()
    text = amfi.fetch_navall()
    kept = st.ingest(amfi.parse(text))
    st.set_meta("last_navall", dt.datetime.now().isoformat(timespec="seconds"))
    after = st.nav_count()
    st.close()
    print(f"daily: parsed_rows_kept={kept} nav_rows {before} -> {after}", flush=True)


def build() -> None:
    st = Store(DB)
    stats = compute.build(st, DIST)
    st.close()
    print(
        f"build: {stats['schemes']} schemes, {stats['dates']} nav dates, "
        f"{stats['categories']} categories, as_of {stats['as_of']}",
        flush=True,
    )


def state_unpack() -> bool:
    ok = unpack(STATE, DB)
    print(f"state-unpack: {'ok' if ok else 'no archive -> full rebuild needed'}", flush=True)
    return ok


def state_pack() -> None:
    st = Store(DB)
    st.pack(STATE)
    st.close()
    print(f"state-pack: {os.path.getsize(STATE)/1e6:.1f} MB", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--years", type=float, default=10.0)
    b.add_argument("--workers", type=int, default=6)
    b.add_argument("--quiet", action="store_true")
    sub.add_parser("daily")
    sub.add_parser("build")
    sub.add_parser("state-unpack")
    sub.add_parser("state-pack")
    a = sub.add_parser("all")
    a.add_argument("--years", type=float, default=10.0)
    a.add_argument("--workers", type=int, default=6)

    args = ap.parse_args(argv)
    os.makedirs(CACHE, exist_ok=True)

    if args.cmd == "backfill":
        backfill(args.years, args.workers, args.quiet)
    elif args.cmd == "daily":
        daily()
    elif args.cmd == "build":
        build()
    elif args.cmd == "state-unpack":
        state_unpack()
    elif args.cmd == "state-pack":
        state_pack()
    elif args.cmd == "all":
        st = Store(DB)
        fresh = st.nav_count() == 0
        st.close()
        if fresh:
            backfill(args.years, args.workers)
        daily()
        build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
