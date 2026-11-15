# MF Ranker

**Mutual-fund analytics for India, computed exclusively from AMFI's own published NAV files.**

No broker feed, no aggregator, no scraping of third-party sites, no paid data. Every figure on
the site traces back to a file AMFI published, and every transformation is in this repository.

▸ **Live:** https://mayankmohan1992.github.io/mf-ranker/
▸ **Scope:** 3,626 published schemes · 42 SEBI categories · 7.6 M NAV rows since October 2016
▸ **Refresh:** automated daily — see [Schedule](#-schedule-and-why-it-runs-then)

---

## ◆ What this is

A static data product answering three questions from official data alone:

```
▸  Which funds are actually good, judged inside their own SEBI category?
▸  What would a monthly SIP have returned, in honest money-weighted terms?
▸  How do up to 20 funds compare over a common window, on risk as well as return?
```

It is a ranking and analytics instrument: every number carries its as-of date, its denominator
and its assumptions. It is **not** investment advice, not a rating agency, and not a screener
built on someone else's derived numbers.

---

## ◆ Data sources — official only

| Source | Provides | Cadence |
|---|---|---|
| `portal.amfiindia.com/spages/NAVAll.txt` | every scheme's latest NAV, plan, option, ISIN (~1.5 MB) | daily |
| `portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx` | full NAV history, requested in month chunks (~24 MB each) | backfill |
| SEBI category taxonomy | the section headers AMFI embeds in its own files | static |

Nothing else is consulted. If a figure cannot be derived from these files, it is not shown.

---

## ◆ Architecture

```
    AMFI files
        │
        ▼
 ┌────────────┐     ┌────────────┐     ┌──────────────┐     ┌───────────────┐
 │   ingest   │────▸│   SQLite   │────▸│    derive    │────▸│  static JSON  │
 │ amfi.py    │     │   store    │     │ compute.py   │     │  + vanilla JS │
 │            │     │ store.py   │     │ sip.py       │     │  (no library) │
 └────────────┘     └────────────┘     │ names.py     │     └───────────────┘
                           │            └──────────────┘             │
                           ▼                                         ▼
                    orphan `state`                          GitHub Pages
                    branch (single                          artifact deploy,
                    commit, force-                          never a data
                    pushed)                                 branch
```

▸ **Store** — one row per scheme per day, `PRIMARY KEY (code, day) WITHOUT ROWID`, dates as
integer days since epoch.
▸ **Derive** — Python writes every byte the browser reads; the front end never recomputes a
return from a separately fetched series, and never needs a server.
▸ **Publish** — a Pages *artifact*. A nightly job that committed data would grow the repository
without bound; the repo stays code-only.
▸ **State** — an orphan branch, force-pushed as one commit per run: durable across runs, no
history to bloat, and immune to Actions-cache eviction.

---

## ◆ What the site does

**Rankings** — trailing returns for `1W · 1M · 3M · 6M · 1Y · 3Y · 5Y · 10Y` (absolute below a
year, CAGR from a year up, actual elapsed days), ranked inside `(category, plan, benchmark
group)`. User-settable top-N and a bottom-N view.

**Ranking basis** — weekly · monthly · quarterly · half-yearly · annual. Each resolves to the
last *completed* bucket, so the five views are genuinely different numbers rather than one
number relabelled, and the header states the as-of date in use.

**SIP simulator** — XIRR for 4 tenures × 5 SIP days with category peer medians, instalment
count, invested-versus-value, and an explicit note when a fund's history begins inside the
window. The amount is free-form because XIRR is money-weighted.

**Comparison** — up to 20 schemes: growth of ₹10,000 over the *common* window, summary across
all windows, calendar-year grid, and weekly return correlation — labelled as correlation, never
as holdings overlap. CSV export and shareable URLs that restore the exact view.

**Detail view** — NAV history, rank history at the selected basis, and the SIP grid.

### Scope decisions

▸ **Growth options only.** IDCW NAVs drop on every payout, so a NAV-based return is wrong for
them and their ranking would be meaningless.
▸ **Direct and Regular ranked separately** — different expense loads; mixing them would flatter
regular plans' peers.
▸ **Index funds and ETFs ranked inside their benchmark group**, sectoral/thematic funds inside
their theme. A pharma fund against a defence fund is arithmetic, not information.
▸ Only schemes with **≥ 2 peers** receive a rank; a unique mandate shows `—` rather than a
fake number.

---

## ◆ Correctness guarantees

Each is enforced in code and covered by a test. The failure mode of financial data is not a
crash — it is a plausible-looking wrong number.

| Invariant | What it prevents |
|---|---|
| **File layout detected by ISIN shape, never by prefix** | `field.startswith("IN")` matched the fund name *"Invesco…"* and silently dropped all 247 Invesco codes from ten years of history |
| **No scheme sampled past a 45-day staleness cutoff** | dead or merged schemes otherwise rank as flat 0% lines and inflate every peer's denominator |
| **Rank denominators published per observation, not as one scalar** | `3/38` was true only for the latest week; every earlier date lied |
| **Compaction keeps exactly the rows the sampler selects** | coarser rules drop the Thursday before a market-holiday Friday and shift every historical return |
| **Integer-day weekday math verified against a known date** | 1970-01-01 was a Thursday, so Friday is `day % 7 == 1`, not `4` |
| **ISIN is the identity** | two codes sharing an ISIN within one plan are the same fund; one ISIN may never span two plans |
| **Non-retail schemes excluded** | AMFI's "Unclaimed Redemption Plan", "Brokerage I.E.F." and one ULIP carry no ISIN and incomparable NAVs |
| **Display names are derived, never destructive** | the official AMFI name stays in `n`; search, tooltips and CSV keep it |
| **NAV is already net of expenses** | TER is reported as a separate fact, never subtracted from a NAV return |

**Release gates:** compact-vs-full build diff, row counts asserted against the source, a
headless-browser audit comparing *every* rendered row to the published JSON (not a spot check),
and every control exercised to confirm it changes what it claims to.

---

## ◆ Verified numbers (this repository, at build time)

| | |
|---|---|
| NAV rows ingested | 7.61 M (10 years, Growth Direct + Regular) |
| Schemes discovered | 7,766 · published (NAV within 45 days) **3,626** |
| Categories | 42 canonical, mapped from 103 distinct AMFI section labels |
| Backfill | 121 monthly AMFI requests, ~4 min single-worker from cache |
| Daily incremental job | ~70 s end to end (restore → ingest → build → deploy) |
| State snapshot | 9.0 MB packed from a ~188 MB store |
| Site payload | category JSON 54–637 KB; one scheme's series ~6 KB |

**Compaction is proven lossless, not assumed:** building from the packed state and from the full
daily store produces byte-identical output across all 42 category files — 0 rank differences,
0 return differences.

---

## ◆ Repository layout

```
pipeline/
  amfi.py        parser for both AMFI layouts; layout chosen by scoring, not guessing
  store.py       SQLite store, compaction, state pack/unpack
  compute.py     returns, ranks, per-basis as-of values, SIP medians, publish step
  sip.py         SIP grid + XIRR (Newton with a bisection fallback)
  names.py       "Fund - Direct Plan - Growth Option"  →  "Fund D-G"
  categories.py  AMFI section label → SEBI category, benchmark/theme grouping
  cli.py         backfill · daily · build · state-pack · state-unpack
web/
  index.html     single page — no framework, no CDN, no build step
  style.css      measured sticky header (--bar-h), dense tabular layout
  app.js         ranking table, detail modal, hand-rolled canvas charts
  sip.js         SIP grid rendering
  compare.js     20-scheme comparison view
tests/
  test_parser.py file-layout fixtures, including the Invesco regression
  test_sip.py    SIP engine vs an independent brute-force implementation
  test_names.py  display-name fixtures + store-wide audit
  test_isin.py   check digits, no shared ISIN, one ISIN never spans two plans
docs/
  ROADMAP.md     feature plan with measured payload costs
.github/workflows/daily.yml
```

---

## ◆ Running it locally

```bash
python3 -m pipeline.cli backfill --years 10 --workers 8   # first run, ~10 min
python3 -m pipeline.cli daily                             # one day's update
python3 -m pipeline.cli build                             # writes dist/
python3 -m http.server -d dist 8000                       # http://localhost:8000
```

Python 3.12, standard library only — there is no `pip install` step, by design. The backfill
caches each month's raw AMFI file under `pipeline/cache/raw/`, so re-parsing is offline and free.

```bash
python3 tests/test_parser.py     # file layouts
python3 tests/test_sip.py        # XIRR engine
python3 tests/test_names.py      # display names
python3 tests/test_isin.py       # identity + plan/category consistency
```

---

## ◆ Schedule, and why it runs then

AMFI's evening refresh was **measured, not assumed**:

```
NAVAll.txt  Last-Modified  : 21:15 IST
that day's NAVs present    : yes, by 22:18 IST   (712 rows)
SEBI deadline for AMCs     : 21:00 IST
```

The file is rewritten through the evening as NAVs arrive and can settle as late as ~23:00–23:30
IST, so the job runs **at least an hour after that window closes**:

| Run | IST | Purpose |
|---|---|---|
| `0 19 * * *` | **00:30** | primary — 3 h 15 m after the observed refresh, ≥ 1 h after a 23:30 worst case |
| `30 22 * * *` | **04:00** | retry — late file or failed run; the pipeline is idempotent |

Every run logs `run started`, `AMFI file Last-Modified` and `build as_of`, so the schedule
proves itself: if `as_of` lags the file date for several days, the cron is running too early.

**Self-healing:** if the `state` branch is missing or the database is empty, the same run
performs the full 10-year backfill before building. There is nothing to do by hand.

---

## ◆ Known limitations

▸ **Growth options only** — IDCW NAVs drop on payout and would rank as false losses.
▸ **No exit load, stamp duty or tax** in any simulation; NAV returns are already post-expense.
▸ **SIP uses a precomputed grid** (4 tenures × 5 days). Arbitrary dates would require shipping
daily series, measured at 89 MB project-wide and rejected in favour of speed.
▸ **Holdings-level overlap is unavailable** from official sources; return correlation is
labelled as the proxy it is.
▸ **Scheme-level AUM, fund managers, exit loads and star ratings** are not published by AMFI or
SEBI, so they are absent rather than approximated.
▸ A handful of legacy AMFI codes carry **no ISIN** (FMP series, brand-new funds) and are
therefore unverifiable; they are reported, never silently trusted.
▸ Where AMFI keeps a legacy section header (`Income`), schemes are grouped as
*Other / Unclassified* rather than guessed into a category.

---

## ◆ Roadmap

Rolling returns and risk metrics, expense ratios from AMFI's own TER endpoint, benchmark and
alpha work on officially sourced index levels, and rank persistence. Effort, ordering and the
measured payload cost behind each: [`docs/ROADMAP.md`](docs/ROADMAP.md).

---

## ◆ Attribution

NAV, plan, option and ISIN data are published by the Association of Mutual Funds in India.
Category structure follows SEBI's mutual-fund classification. This project is an independent
analytics layer over those public files and is not affiliated with AMFI or SEBI.
