# MF Ranker — Feature Roadmap

Planning doc. Every feature below is buildable from **official sources only** (AMFI, SEBI, NSE/BSE, RBI/FBIL) and runs on the existing static pipeline — no backend, no database, no nightly import.

Current state: 3,637 published schemes · 42 SEBI categories · 7.61M NAV rows back to 2016-10 · 156 weeks of rank history · daily rebuild ~60s into a Pages artifact · `dist` 30 MB.

Sections marked **[measured]** were verified by prototyping today, not estimated.

---

## 0. Guardrails

1. **Official sources only.** AMFI (NAV, TER, tracking error, benchmark names, riskometer) · SEBI (category and cost rules) · NSE/BSE (index levels) · RBI/FBIL (risk-free rate). No Value Research, Morningstar, Tickertape, mfapi.in, Groww — not even as a cross-check inside the shipped build.
2. **Static only.** Everything the browser needs is precomputed into JSON at build time or computed client-side. No server, no secrets, no API keys in the frontend.
3. **NAV is already net of expenses.** Never subtract TER from a NAV return. Cost is reported as a separate fact.
4. **Growth options only, Direct + Regular.** IDCW NAVs drop on payout and would rank as fake losses.
5. **Every number carries its as-of date and its denominator.**
6. **The daily job's shape does not change**: restore state → ingest → build → deploy artifact → push state.

---

## 1. What the data can and cannot support

| Dataset | Official source | Granularity | Status | Unlocks |
|---|---|---|---|---|
| NAV | AMFI `NAVAll.txt` + `DownloadNAVHistoryReport` | daily | **live** | everything |
| Expense ratio (Direct/Regular, split: base + brokerage + transaction + levies) | AMFI `/api/populate-te-rdata-revised` | month | verified, not wired | F5 |
| Benchmark name + tracking error | AMFI `/api/tracking-error-data` | monthly | verified, not wired | F6, F7 |
| Tracking difference | AMFI `/api/tracking-difference` | period | endpoint found, params TBD | F7 |
| Riskometer / PR-Credit-Market-Liquidity | AMFI `/risk-parameters` | monthly | page exists, params TBD | F4 display |
| Index levels, **price** (all Nifty indices, daily OHLC + P/E + P/B + **dividend yield**) | NSE `archives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv` | daily, 1 file/day | **[measured] verified working** | F6 (as TR proxy) |
| Index levels, **TRI** (what AMFI calls the benchmark) | niftyindices.com `/BackPage/*` POST API | daily | **[measured]** endpoint live but payload buried in `developer.js`; needs one session of reverse-engineering | F6 (exact) |
| BSE indices | `api.bseindia.com` | daily | **[measured]** plain curl → "Access Denied"; needs browser headers/referer | F6 alt |
| 91-day T-bill | RBI DBIE / FBIL | daily | not wired | Sharpe |
| Category + TER rules | SEBI circulars | static text | not wired | UI citations |

**Not available from official sources — do not build:**

| Wanted | Why not |
|---|---|
| Portfolio holdings / true overlap | Only in 40+ AMC monthly portfolio PDFs (SEBI-mandated). Official, but a separate ingestion project — see §9. Return correlation is the honest proxy until then. |
| Scheme-level AUM | AMFI publishes AUM by AMC and category, not per scheme |
| Fund manager, exit load, minimum investment | AMC documents only |
| Star ratings | Third-party by definition; SEBI has warned on them |
| Real-time NAV | Published once daily |

---

## 2. F1 — SIP simulator *(requested)*

**Why.** SIP is how most retail money enters funds, and trailing CAGR systematically misleads about it — a fund with a great 5Y CAGR can have a mediocre SIP XIRR if it fell early in the window.

**Inputs.** Scheme (1, or up to 20 in compare mode) · start date · monthly amount (default ₹5,000) · SIP day 1–28 (default 5) · optional annual step-up % (default 0) · optional initial lump sum.

**Outputs.**
- Instalments made, total invested, current value, absolute gain
- **XIRR** (headline) plus simple absolute %
- SIP vs lumpsum of the same total invested at start — explicitly labelled illustrative, not a fair fight
- Category median SIP XIRR for the identical schedule, and the fund's position within it
- Chart: invested (step line) vs portfolio value
- Per-instalment table (date, NAV used, units) — collapsible
- Best/worst instalment: which month bought cheapest units

**Computation.**
- Buy at the **first available NAV on or after** the target date; if the month has none, use the month's last NAV; if the fund had not launched, skip the month and say so.
- XIRR by bisection on NPV, brackets `[-0.999, 10]`, tolerance 1e-9; **report n/a when NPV has no sign change** instead of returning a wrong root.
- Step-up applies at each 12-instalment boundary.
- **XIRR is scale-invariant across amount**, so the grid can be precomputed once and serve any amount the user types.

**Two tiers (this is the design that keeps it cheap).**
1. **Default — precomputed grid.** Start ∈ {1, 2, 3, 5, 7, 10} years ago × day ∈ {1, 5, 10, 15, 25}, computed at build time. Zero extra network, works for all 3,637 schemes, instant. Covers ~95% of real questions.
2. **Optional "custom dates" toggle** — fetches a per-scheme daily file lazily **[measured]** ~11 KB gzipped/scheme. Ship this only if the grid feels limiting in practice.

**Edge cases that must be handled, not ignored**
- Fund launched mid-window → start at first available month, state it.
- **Never assume trading days.** 3.35% of NAV rows are Sat/Sun, concentrated in Liquid/Overnight/FTP funds that legitimately declare daily. (There are also 153 stray weekend rows in Large Cap — data noise, not signal.)
- Renamed/merged schemes keep the ISIN but may change the AMFI code, so a series can split — flag series that begin inside the window.
- ELSS: warn when tenure < 3 years (lock-in).
- Exit load, stamp duty, STT: **not modelled** — stated in the footer.

**Data.** Precomputed `sip` block per scheme; peer medians per category. **Effort:** M. **Done when** a hand-built spreadsheet SIP (24 instalments, one falling on a holiday, one on a fund's launch month) matches the UI to 2 dp.

---

## 3. F2 — Compare up to 20 schemes *(requested)*

**Why.** The most-used interaction on any fund site, and the one that exposes how meaningless a lone rank is.

**Selection.** Checkbox column + floating compare tray (chips, count, clear). Hard cap 20 with a clear message. Cross-category allowed, with a warning that ranks are not comparable across categories.

**Views**
1. **Summary table** — trailing returns (8 windows), rank/N per window, category, plan, TER (once F5 lands)
2. **Growth of ₹10,000** — series normalised to the *common* window start; toggle series; hover crosshair reading all values
3. **Risk table** — volatility, Sharpe, Sortino, max drawdown, drawdown duration, % positive months, best/worst month
4. **Rolling 3Y band** — min/median/max, consistency rather than one endpoint
5. **Calendar-year grid** — 2017 … YTD
6. **Return-correlation matrix** — labelled *"return correlation, not holdings overlap"*
7. **SIP XIRR row** — the same schedule applied to all 20

**Fairness rules (the part that makes or breaks it)**
- Compare over the **intersection** of available histories; print the window (`compared 2021-11-15 → 2026-11-15`).
- A scheme covering <80% of that window is greyed with a warning, never silently included.
- Rank-within-selected-set on the same window, never on different endpoints.

**Cost.** Zero extra network beyond the category file plus each scheme's existing 5.7 KB weekly series — every metric in views 3/4/7 is precomputed. **Effort:** M. **Done when** 20 schemes paint in under 500ms and the share URL round-trips to identical numbers.

**Extras.** CSV export per table; **shareable URL** encoding full state (`?cat=…&win=…&basis=…&cmp=code,code,…`) so a comparison can be sent with no backend.

---

## 4. Payload & data model — revised after measuring

Measured today on 40 long-history schemes: a naive daily array (base day + day gaps + paise values) is **25 KB raw / 11.2 KB gzipped per scheme → 89 MB raw / 40 MB gzipped project-wide**. That is far too heavy to ship by default.

So the design is **precompute first, raw data never**:

| Block | Contents | Size/scheme |
|---|---|---|
| `sip` | grid: 6 starts × 5 days → {XIRR×10, value/invested×1000} | ~250 B |
| `risk` | vol, Sharpe, Sortino, max DD + dates, recovery days, % positive months | ~150 B |
| `roll` | rolling 1Y/3Y/5Y p10/p50/p90 + % beating peer median | ~120 B |
| `v` (exists) | 522 weekly NAVs — chart only | 5.7 KB file already |
| `h` (exists) | 156 weekly ranks | — |
| `cat/<slug>.json` | peer medians: SIP grid, rolling, category stats | +20–40 KB/category |

Total added: **~0.5 KB per scheme, ≈2 MB to `dist`**. Everything instant, nothing fetched per click.

If custom-date SIP is later judged necessary, add a **separate** `s/<code>.d.json` (daily, ~11 KB gzip) fetched only when that toggle is used — never in the default path.

---

## 5. Recommended features beyond the two asked for

Ranked by value per unit of work; all officially sourced.

### F3 — Rolling returns & consistency *(S — highest value)*
1Y/3Y/5Y rolling at monthly steps across the full history: p10 / median / p90, worst window, and **% of windows beating the category median**. The antidote to "top of the table because of one lucky endpoint".

### F4 — Risk & drawdown *(M)*
Volatility, Sharpe (risk-free from RBI 91-day T-bill, shipped as a tiny daily JSON), Sortino, max drawdown with dates, recovery time, % positive months, plus an **underwater chart** in the detail modal — the fastest way to convey "how bad did it get".

### F5 — Cost intelligence from AMFI TER *(M — differentiator)*
Endpoint already verified: scheme-level TER, Direct and Regular, split into base expense + brokerage + transaction + statutory levies, monthly since 2022.
- Expense-ratio column; Direct-vs-Regular **rupee gap** over 1/3/5 years on ₹1L
- TER trend line in the detail modal
- "Cheapest in category" tab and a **cost-vs-return scatter**
- Cost-rank inside each category

### F6 — Benchmark & alpha *(L — exact TRI needs work, proxy is ready today)*
AMFI's tracking-error endpoint supplies the **official benchmark name per scheme**, which solves the mapping problem that otherwise makes index series unusable.
- **Ready now:** NSE archive CSV gives every index's daily close *and dividend yield*, so total return ≈ price return + yield — an official-source proxy, clearly labelled as a proxy.
- **Exact path:** reverse-engineer the niftyindices.com TRI POST (endpoint is live; one session of work) or drive BSE through a browser context.
- Then: excess return, beta, alpha, information ratio, up/down capture — and authoritative benchmark groups replacing the name-parsed ones.

### F7 — Index-fund scoreboard *(S — AMFI only, no index series needed)*
For 749 index funds + 39 ETFs, return alone is meaningless when the index differs. Rank on **tracking error**, **tracking difference** and TER — the three things that actually distinguish one Nifty 50 fund from another.

### F8 — Rank persistence *(S — data already stored)*
From the 156 weeks of ranks: average rank, % of weeks in the top quartile, longest top-10 streak, rank volatility. "Consistently good, or good once?" — nobody free does this per SEBI category.

### F9 — Category dashboard *(M)*
Per category: median and dispersion, how many funds beat the category average, best/worst, spread across windows, how many have a full 5Y record. Context that makes a single rank interpretable.

### F10 — Portfolio builder *(L, later)*
N schemes with weights → blended return and risk, effective number of funds, drift after a rebalance period. Reuses F2's correlation matrix.

### F11 — Tax view *(M, optional)*
Post-tax XIRR with LTCG/STCG and the ₹1.25L equity exemption, as a clearly-labelled simulation with editable, **dated** assumptions. Rules are law (official), but they change.

### F12 — Watchlist, digest, sharing *(S)*
`localStorage` watchlist; CI writes `watchlist-digest.json` (rank movers, entrants, exits) plus an RSS feed so updates arrive with no email infrastructure. Plus the shareable URLs from F2.

### F13 — Trust panel *(S — do early)*
As-of date, NAVs ingested, published vs discovered schemes, unmatched/renamed schemes, and a periodic cross-check of computed returns against AMFI's own published figures. Cheap, and it separates "a website" from "a data product".

---

## 6. Sequencing

| Sprint | Contents | Why this order |
|---|---|---|
| 1 | §4 precompute blocks + **F1 SIP** + **F2 Compare** | Both requested features need the same precomputed blocks; ship the foundation once |
| 2 | **F3 rolling** + **F4 risk/drawdown** | Same data, makes comparison substantive instead of cosmetic |
| 3 | **F5 TER** | New source but isolated; biggest "why is this site different" payoff |
| 4 | **F7 index scoreboard** → **F6 benchmark** | F7 is AMFI-only and cheap; F6 needs the index-series work |
| 5 | **F8 rank persistence** + **F9 category dashboard** | Pure recompute of data already stored |
| 6 | **F13 trust panel**, **F12 watchlist/share**, then **F10/F11** if wanted | Polish, then the heavy optional items |

Every sprint must keep the daily job green: build under ~5 minutes, deployable artifact, no manual steps.

---

## 7. Correctness rules

1. **XIRR by bisection, never a "try IRR" loop** — return n/a when there is no sign change.
2. **Never assume trading days** — 3.35% of rows are weekend NAVs (legitimately so for Liquid/Overnight/FTP).
3. **Compare over intersection**, never over each fund's own best window.
4. **Rates: absolute % under a year, CAGR from a year up**, using actual elapsed days (`365.25/days`).
5. **A rank is meaningless without its group** — sectoral within theme, index funds within benchmark group; F6 makes those groups authoritative.
6. **Peer medians are precomputed at build time**; the browser must never need to fetch every peer.
7. **Every simulation states its assumptions** (no exit load, no STT, growth only, NAV post-expense).
8. **Cross-check one number per feature against AMFI's own published figure** before shipping it.

---

## 8. Test gates per feature

- Hand-computed spreadsheet fixture (SIP: 24 instalments, one on a holiday, one on a launch month; XIRR to 2 dp).
- Deterministic replay: same inputs → identical output after a rebuild.
- DOM-vs-JSON equality for **every** rendered row, not a spot check.
- Share-URL round trip reproduces exact numbers.
- Every control changes what it claims to (the basis bug's lesson).
- Cold start: no state branch → backfill → build → deploy still green.

---

## 9. Explicitly out of scope

- **Holdings-level overlap** — official only via 40+ AMC monthly portfolio PDFs. A separate ingestion project; until then return correlation, labelled as a proxy.
- **Scheme AUM / fund manager / exit load / ratings** — not published by AMFI or SEBI.
- **Advice or "best fund" claims** — ranking and analytics only; copy stays neutral.
- **Any paid or third-party feed**, including as a fallback.

---

## 10. Open decisions

1. **Custom-date SIP**: precomputed grid only (cheap, instant) or also ship per-scheme daily files (~+40 MB, exact for any date)?
2. **Compare across categories**: allow with a warning, or restrict to one category?
3. **Next data source**: TER (ready now, official) or benchmark/index work (bigger, partly blocked)?
4. **Tax view**: build with dated, editable assumptions or skip?
