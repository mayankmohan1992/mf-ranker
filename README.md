# MF Ranker

Mutual fund rankings for India, computed only from **AMFI**'s own published NAV
files. No broker data, no paid feed, no scraping of third-party sites.

**Live:** https://<owner>.github.io/mf-ranker/ *(set once Pages is enabled)*

---

## What it does

* Downloads every scheme's NAV from AMFI — a 10-year backfill plus a daily update.
* Classifies each scheme with the **AMFI/SEBI category carried in AMFI's own file
  structure** (`Open Ended Schemes(Equity Schemes - Large Cap Fund)`), not by
  guessing from fund names.
* Computes trailing returns for **1W · 1M · 3M · 6M · 1Y · 3Y · 5Y · 10Y**
  (absolute below a year, CAGR from a year up) on a weekly Friday grid.
* Ranks every scheme inside its **(category, plan)** group at every week, and
  keeps the full rank history so the dashboard can show **weekly / monthly /
  quarterly / half-yearly / annual** views from one consistent series.
* Serves a static dashboard: top/bottom *N* per category (default 20), and a
  per-scheme view with NAV history plus rank-within-category over time.

## Data source

| What | Endpoint |
|---|---|
| Latest NAV, all schemes | `https://portal.amfiindia.com/spages/NAVAll.txt` |
| Historical NAV, all schemes | `https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx?frmdt=&todt=` |

Both are AMFI's official files. The historical endpoint returns *all* schemes for
a date range (~24 MB per month), so the backfill is chunked by month and cached.

### Scope decisions

* **Growth option only.** IDCW NAVs drop on every payout, so a NAV-based return
  for them is wrong and their ranking would be meaningless.
* **Direct + Regular plans**, ranked separately — different expense loads, so
  mixing them in one rank list would flatter regular plans' peers.
* **Index funds and ETFs** are ranked inside their benchmark group
  (Nifty 50 vs Nifty 50, gold ETF vs gold ETF), and **Sectoral/Thematic** funds
  inside their theme. Ranking a pharma fund against a defence fund is arithmetic,
  not information.
* Only schemes with **≥ 2 peers** get a rank; a genuinely unique mandate shows
  `—` instead of a fake number.

## Architecture

```
pipeline/amfi.py        download + parse AMFI text files (robust to old/new column layouts)
pipeline/categories.py  AMFI section label -> canonical SEBI category, benchmark/theme groups
pipeline/store.py       SQLite NAV store (one row per scheme per date)
pipeline/compute.py     weekly grid -> returns -> ranks -> static JSON
pipeline/cli.py         backfill | daily | build | state-pack | state-unpack | all
web/                    hand-written vanilla HTML/CSS/JS dashboard (no libraries)
```

### How the daily automation works (no manual intervention)

```
cron (23:30 IST)  ->  restore NAV store from `state` branch
                  ->  append today's NAVAll.txt
                  ->  recompute returns + ranks
                  ->  force-push a single-commit `state` branch
                  ->  deploy dist/ to GitHub Pages as a workflow artifact
```

* **Nothing is committed to `main` daily.** Pages is deployed from an artifact,
  so the repository does not grow by data files every night.
* **The NAV store lives on an orphan `state` branch** that is force-pushed as a
  single commit each run — durable across runs, but with no history to bloat the
  repo (an Actions cache would be evicted after 7 idle days).
* **Self-healing:** if the `state` branch is missing or the DB is empty, the same
  workflow runs the full 10-year backfill before building. Nothing to do by hand.
* A second run at 02:00 IST covers the days AMFI publishes late.

## Local use

```bash
python3 -m pipeline.cli backfill --years 10 --workers 6   # one-time, ~10 min
python3 -m pipeline.cli daily                             # today's NAV
python3 -m pipeline.cli build                             # -> dist/
python3 -m http.server -d dist 8000                       # open http://localhost:8000
```

`backfill` caches each month's raw AMFI file under `pipeline/cache/raw/`, so
re-parsing costs nothing but network-free seconds.

## Verified numbers (this repo, at build time)

| | |
|---|---|
| NAV rows ingested | 7.39 M (10 years, all Growth Direct+Regular schemes) |
| Schemes discovered | 7,557 · published (NAV within 45 days) 3,637 |
| Categories | 42 canonical, from 103 distinct AMFI section labels |
| Backfill | 121 monthly AMFI requests, ~10 min at 7 workers |
| Daily incremental job | **~70 s** end to end (restore → ingest → build → deploy) |
| State snapshot | 8.7 MB packed (from a 188 MB store) |
| Site payload | category JSON 29–340 KB; one scheme's series ~8 KB |

**Compaction is proven lossless, not assumed:** building the whole site from the
8.7 MB state and from the 188 MB full daily store produces byte-identical output
for all 42 category files, 0 rank differences and 0 return differences.

## Known limits

* NAV history is what AMFI publishes; a scheme merged or renamed keeps the NAV
  series of its old code, so pure-rename continuations can appear as two schemes.
* Rank history is weekly for the last ~3 years, NAV series weekly for ~10 years.
* A scheme is only counted in a ranking while its NAV is at most 30 days old at
  that point. Schemes that stopped publishing (merged, closed, renamed) do not
  linger as flat 0% lines - they drop out of the peer set on the date they stop
  reporting, which is what keeps historical group sizes honest.
* Returns are not adjusted for exit load, taxes, or IDCW payouts (by design —
  growth option only).
* AMFI's categorisation is authoritative here; where AMFI keeps a legacy section
  header (`Income`), those schemes are grouped as *Other / Unclassified* rather
  than guessed into a category.

## SIP simulator and comparison (Sprint 1)

- **SIP grid** — XIRR for 4 tenures (1/3/5/10Y) x 5 SIP days, precomputed at build time
  from the daily NAV series (`pipeline/sip.py`). XIRR is money-weighted, so the amount the
  user types only scales the rupee figures, never the rate.
- Instalments buy at the **first NAV published on or after** the chosen day; months with no
  NAV are skipped, never back-dated. A single instalment or a window under 60 days yields
  no annualised rate (n/a) rather than an absurd number, and the grid records how many days
  late the first instalment landed so a "10Y SIP" on a 2-year-old fund is labelled honestly.
- **Peer medians** per category/plan are precomputed into the category file, so a fund is
  ranked against its category's SIP performance without fetching every peer.
- **Compare up to 20 schemes**: growth of Rs 10,000 over the common window, summary across
  all 8 windows, calendar-year grid, weekly return correlation (explicitly *not* holdings
  overlap), CSV export and a shareable URL that restores the exact view.

Tests: `python3 tests/test_parser.py` and `python3 tests/test_sip.py`.
