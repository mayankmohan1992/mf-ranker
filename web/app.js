/* MF Ranker — vanilla single page, no dependencies.
   Data: static JSON produced by pipeline/compute.py from AMFI NAV files. */

const S = {
  meta: null, cats: [], slug: null, cat: null,
  plan: 'Direct', win: '1Y', basis: 'weekly', dir: 'top', n: 20,
  sort: 'ret', sortDesc: true, span: '1Y', sel: null, search: '',
  series: {}, cmp: [], cmpOpen: false,
};

let VISIBLE = [];

const $ = (id) => document.getElementById(id);
const fmtPct = (v) => (v === null || v === undefined) ? '—' : (v > 0 ? '+' : '') + v.toFixed(2) + '%';
const cls = (v) => v === null || v === undefined ? 'muted' : (v > 0 ? 'pos' : v < 0 ? 'neg' : 'muted');
const fmtNav = (v) => v === null || v === undefined ? '—' : v.toFixed(2);

/* ---------------- layout ---------------- */
/* The topbar is sticky and wraps to two lines on narrow windows, so its height is
   measured rather than assumed: the sticky table header and the sidebar offset
   both hang off this variable. */
function syncTopbarHeight() {
  const h = document.querySelector('.topbar').getBoundingClientRect().height;
  document.documentElement.style.setProperty('--topbar-h', Math.round(h) + 'px');
}
window.addEventListener('resize', syncTopbarHeight);
window.addEventListener('load', syncTopbarHeight);

/* ---------------- boot ---------------- */
async function boot() {
  syncTopbarHeight();
  if (window.ResizeObserver) {
    new ResizeObserver(syncTopbarHeight).observe(document.querySelector('.topbar'));
  }
  S.meta = await (await fetch('data/meta.json')).json();
  $('asOf').textContent = S.meta.as_of;
  $('builtAt').textContent = S.meta.generated_at.replace('T', ' ').replace('Z', ' UTC');
  $('schemeCount').textContent = S.meta.categories.reduce((a, c) => a + c.count, 0).toLocaleString();

  const win = $('win');
  S.meta.windows.forEach((w) => {
    const o = document.createElement('option');
    o.value = w.key; o.textContent = w.label + (w.annualised ? ' (CAGR)' : '');
    win.appendChild(o);
  });
  win.value = S.win;

  // a share link reproduces the exact view: category, window, basis, count, compare set
  const q = new URLSearchParams(location.search);
  if (q.get('win')) S.win = q.get('win');
  if (q.get('basis')) S.basis = q.get('basis');
  if (q.get('dir')) S.dir = q.get('dir');
  if (q.get('plan')) S.plan = q.get('plan');
  if (q.get('n')) S.n = Math.max(1, Math.min(500, Number(q.get('n')) || 20));
  $('n').value = S.n;
  win.value = S.win;
  $('basis').value = S.basis;
  $('dir').value = S.dir;
  [...$('planSeg').children].forEach((b) => b.classList.toggle('on', b.dataset.plan === S.plan));

  buildCatNav();
  const preferred = S.meta.categories.find((c) => c.slug === 'large-cap-fund')
    || S.meta.categories.slice().sort((a, b) => b.count - a.count)[0];
  if (q.get('cat') && S.meta.categories.some((c) => c.slug === q.get('cat'))) {
    await selectCat(q.get('cat'));
  } else if (preferred) await selectCat(preferred.slug);

  $('btnCompare').onclick = () => openCompare();
  $('btnClearCmp').onclick = () => { S.cmp = []; updateTray(); render(); };
  $('cmpBack').onclick = () => closeCompare();
  $('cmpCsv').onclick = () => compareCsv();
  $('cmpShare').onclick = () => shareLink();
  $('sipAmt').oninput = () => {
    const cur = S.cat && S.sel ? S.cat.schemes.find((x) => x.c === S.sel) : null;
    if (cur) renderSipResult(cur);
  };
  $('selAll').onchange = (e) => {
    if (e.target.checked) {
      VISIBLE.forEach((c) => { if (S.cmp.length < MAX_CMP && !S.cmp.includes(c)) S.cmp.push(c); });
    } else {
      S.cmp = S.cmp.filter((c) => !VISIBLE.includes(c));
    }
    updateTray(); render();
  };
  if (q.get('cmp')) {
    S.cmp = q.get('cmp').split(',').filter(Boolean).slice(0, MAX_CMP);
    updateTray();
    if (S.cmp.length) await openCompare();
  } else {
    updateTray();
  }

  win.onchange = () => { S.win = win.value; render(); };
  $('basis').onchange = (e) => {
    S.basis = e.target.value;
    render();                       // ranks + header + ordering all depend on the basis
    if (!$('modal').hidden && S.sel) {
      const cur = S.cat.schemes.find((x) => x.c === S.sel);
      if (cur) openDetailMeta(cur);
      drawDetail();
    }
  };
  $('dir').onchange = (e) => {
    S.dir = e.target.value;
    S.sort = 'ret';
    S.sortDesc = true;              // reset direction: 'rank' sorting leaves this false
    render();
  };
  $('n').onchange = (e) => { S.n = Math.max(1, Math.min(500, +e.target.value || 20)); render(); };
  $('search').oninput = (e) => { S.search = e.target.value.toLowerCase().trim(); render(); };
  $('planSeg').onclick = (e) => {
    const b = e.target.closest('button'); if (!b) return;
    [...$('planSeg').children].forEach((x) => x.classList.toggle('on', x === b));
    S.plan = b.dataset.plan; closeModal(false); render();
  };
  $('spanSeg').onclick = (e) => {
    const b = e.target.closest('button'); if (!b) return;
    [...$('spanSeg').children].forEach((x) => x.classList.toggle('on', x === b));
    S.span = b.dataset.span; if (S.sel) drawDetail();
  };
  document.querySelectorAll('th.sortable').forEach((th) => {
    th.onclick = () => {
      const key = th.dataset.sort;
      // name and rank read best-first; return and fund house read biggest-first
      if (S.sort === key) S.sortDesc = !S.sortDesc;
      else { S.sort = key; S.sortDesc = !(key === 'name' || key === 'rank'); }
      render();
    };
  });
  window.addEventListener('resize', () => {
    syncTopbarHeight();
    if (!$('modal').hidden && S.sel) drawDetail();
  });
  $('closeModal').onclick = () => closeModal();
  $('modal').querySelector('[data-close]').onclick = () => closeModal();
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('modal').hidden) closeModal();
  });
}

function buildCatNav() {
  const groups = { Equity: [], Debt: [], Hybrid: [], Other: [] };
  S.meta.categories.forEach((c) => (groups[c.asset] || groups.Other).push(c));
  const nav = $('catNav');
  nav.innerHTML = '';
  Object.entries(groups).forEach(([asset, cats]) => {
    if (!cats.length) return;
    const h = document.createElement('div');
    h.className = 'cat-group'; h.textContent = asset + ' · ' + cats.length;
    nav.appendChild(h);
    cats.forEach((c) => {
      const b = document.createElement('button');
      b.className = 'cat-item'; b.dataset.slug = c.slug;
      b.innerHTML = `<span>${c.name}</span><span class="count">${c.count}</span>`;
      b.onclick = () => selectCat(c.slug);
      nav.appendChild(b);
    });
  });
}

async function selectCat(slug) {
  if (S.slug === slug) return;
  S.slug = slug;
  document.querySelectorAll('.cat-item').forEach((b) => b.classList.toggle('on', b.dataset.slug === slug));
  S.cat = await (await fetch(`data/cat/${slug}.json`)).json();
  closeModal(false);
  render();
}

/* ---------------- table ---------------- */
function currentWindowLabel() {
  const w = S.meta.windows.find((x) => x.key === S.win);
  return w ? w.label : S.win;
}

function basisLabel() {
  const b = (S.meta.bases || []).find((x) => x.key === S.basis);
  return b ? b.label : S.basis;
}
function basisAsOf() { return (S.meta.basis_asof || {})[S.basis] || ''; }
/* per-basis values arrive as positional arrays in meta.bases order */
function basisIndex() {
  const i = (S.meta.bases || []).findIndex((b) => b.key === S.basis);
  return i < 0 ? 0 : i;
}
function atBasis(arr) {
  if (!arr) return null;
  const v = arr[basisIndex()];
  return v === undefined ? null : v;
}
function rankOf(s) { return atBasis(s.k[S.win]); }
function totalOf(s) { return atBasis(s.N[S.win]); }
function deltaOf(s) { return atBasis(s.d[S.win]); }

function render() {
  syncTopbarHeight();   // cheap re-measure: also self-corrects if a resize event was missed
  if (!S.cat) return;
  $('catTitle').textContent = S.cat.name;
  const planTotal = S.cat.schemes.filter((s) => s.p === S.plan).length;
  $('catMeta').innerHTML = `${S.cat.asset} · ${planTotal} ${S.plan} growth schemes `
    + `· ranked by ${currentWindowLabel()} return `
    + `${S.cat.schemes.some((s) => s.g) ? '· index/theme funds ranked within their own benchmark' : ''}`;
  $('thRet').textContent = currentWindowLabel();
  const asOf = basisAsOf();
  $('thRank').innerHTML = `Rank <span class="basis">· ${basisLabel()}</span>`;
  const ABBR = { weekly: 'WK', monthly: 'MTH', quarterly: 'QTR', halfyearly: 'HY', annual: 'YR' };
  const prevAsOf = (S.meta.basis_prev_asof || {})[S.basis];
  $('thDelta').innerHTML = `Δ <span class="basis">${ABBR[S.basis] || ''}</span>`;
  $('thDelta').title = prevAsOf && asOf
    ? `Change in ${currentWindowLabel()} rank vs the previous ${basisLabel().toLowerCase()} `
      + `(${prevAsOf} -> ${asOf}). ▲ = moved up, ▼ = moved down.`
    : `Change in ${currentWindowLabel()} rank`;
  $('thRank').title = asOf
    ? `${currentWindowLabel()} rank within category, ${basisLabel().toLowerCase()} as of ${asOf}`
    : `${currentWindowLabel()} rank within category`;
  $('ctxHint').textContent = `Showing ${S.dir === 'top' ? 'top' : 'bottom'} ${S.n} of ${planTotal}`
    + (S.dir === 'top' ? '' : ' — worst first')
    + (asOf ? ` · ranks as of ${asOf} (${basisLabel().toLowerCase()})` : '');

  let rows = S.cat.schemes.filter((s) => s.p === S.plan);
  if (S.search) {
    rows = rows.filter((s) => (s.dn || '').toLowerCase().includes(S.search)
      || s.n.toLowerCase().includes(S.search));
  }
  // Keep funds that have no return for the selected window when the user is searching
  // for them by name - otherwise a brand-new fund is unreachable ("No schemes match")
  // even though it has a NAV chart and a SIP grid.
  if (!S.search) rows = rows.filter((s) => s.r[S.win] !== null);
  rows.sort((a, b) => {
    const pick = (s) => S.sort === 'name' ? s.n.toLowerCase() : S.sort === 'amc' ? (s.a || '').toLowerCase()
      : S.sort === 'rank' ? (rankOf(s) ?? 1e9)
        : (S.sort === 'ret' ? (s.r[S.win] ?? -1e9) : s.n.toLowerCase());
    const x = pick(a), y = pick(b);
    if (x === y) return a.n.localeCompare(b.n);
    return (x > y ? 1 : -1) * (S.sortDesc ? -1 : 1);
  });
  if (S.sort === 'ret' && S.dir === 'bottom') rows.reverse();
  rows = rows.slice(0, S.n);

  const tb = $('rows');
  tb.innerHTML = '';
  rows.forEach((s, i) => {
    const rk = rankOf(s);
    const dv = deltaOf(s);                            // positive = improved (rank number fell)
    let delta = '<span class="muted">—</span>';
    if (dv !== null && dv !== undefined && dv !== 0) {
      delta = `<span class="${dv > 0 ? 'pos' : 'neg'}">${dv > 0 ? '▲' : '▼'} ${Math.abs(dv)}</span>`;
    }

    const tr = document.createElement('tr');
    if (S.sel === s.c) tr.className = 'on';
    const checked = S.cmp.includes(s.c) ? ' checked' : '';
    tr.innerHTML = `
      <td class="selcol"><input type="checkbox" data-code="${s.c}"${checked}
        aria-label="Select for comparison" title="Select for comparison"></td>
      <td class="num muted">${i + 1}</td>
      <td class="name" title="${s.n.replace(/"/g, '&quot;')}"><b>${s.dn || s.n}</b>${s.g ? `<span class="tag">${s.g}</span>` : ''}</td>
      <td class="muted">${s.a || '—'}</td>
      <td class="num ${cls(s.r[S.win])}">${fmtPct(s.r[S.win])}</td>
      <td class="num" title="${rk !== null && totalOf(s)
        ? `ranked ${rk} of ${totalOf(s)} ${S.plan} schemes that had a ${currentWindowLabel()} record on ${asOf}`
          + ` (${planTotal} in the category)`
        : `no ${currentWindowLabel()} record on ${asOf}`}"
        ><span class="rankpill">${rk ?? '—'}${rk !== null && totalOf(s) ? ' / ' + totalOf(s) : ''}</span></td>
      <td class="num">${delta}</td>`;
    tr.onclick = () => { S.sel = s.c; render(); openDetail(s); };
    const cb = tr.querySelector('input[type="checkbox"]');
    cb.onclick = (e) => { e.stopPropagation(); toggleCmp(s.c, cb.checked); };
    tb.appendChild(tr);
  });
  VISIBLE = rows.map((s) => s.c);
  const allBox = $('selAll');
  if (allBox) {
    allBox.checked = VISIBLE.length > 0 && VISIBLE.every((c) => S.cmp.includes(c));
    allBox.indeterminate = !allBox.checked && VISIBLE.some((c) => S.cmp.includes(c));
  }
  $('empty').hidden = rows.length > 0;
}

/* ---------------- detail ---------------- */
async function loadSeries(code) {
  if (S.series[code]) return S.series[code];
  const res = await fetch(`data/s/${code}.json`);
  if (!res.ok) throw new Error('series ' + code + ' ' + res.status);
  const raw = await res.json();
  // 0 encodes "no value" (never a valid NAV or rank)
  const nav = raw.v.map((v) => (v === 0 ? null : v));
  const h = {};
  Object.keys(raw.h).forEach((k) => { h[k] = raw.h[k].map((v) => (v === 0 ? null : v)); });
  S.series[code] = { nav, h, sip: raw.sip || null, cy: raw.cy || {} };
  return S.series[code];
}

function openModal() {
  const m = $('modal');
  if (m.hidden) {
    m.hidden = false;
    document.body.classList.add('modal-open');
  }
}

function closeModal(doRender = true) {
  const m = $('modal');
  if (m && !m.hidden) {
    m.hidden = true;
    document.body.classList.remove('modal-open');
  }
  S.sel = null;
  if (doRender) render();
}

function openDetailMeta(s) {
  $('dName').textContent = s.dn || s.n;
  $('dName').title = s.n;
  const asOf = basisAsOf();
  $('dMeta').innerHTML = `${s.a || '—'}${s.g ? ' · ' + s.g : ''} · ${S.plan} plan · ${S.cat.name}`
    + (asOf ? ` · ranks as of ${asOf} (${basisLabel().toLowerCase()})` : '');
}

async function openDetail(scheme) {
  const s = scheme || S.cat.schemes.find((x) => x.c === S.sel);
  if (!s) return;
  openModal();
  openDetailMeta(s);
  $('dStats').innerHTML = '<div class="stat"><div class="lab">loading</div><div class="val muted">…</div></div>';
  try {
    s._series = await loadSeries(s.c);
  } catch (e) {
    $('dStats').innerHTML = '<div class="stat"><div class="lab">error</div><div class="val neg">series unavailable</div></div>';
    return;
  }
  if (S.sel === s.c) { drawDetail(s); renderSip(s); }
}

function drawDetail(scheme) {
  const s = scheme || (S.cat.schemes.find((x) => x.c === S.sel) || null);
  if (!s || !s._series) return;
  const ser = s._series;
  openDetailMeta(s);      // single source for the header line (name, category, rank as-of)

  const stats = $('dStats');
  stats.innerHTML = '';
  S.meta.windows.forEach((w) => {
    const v = s.r[w.key];
    const rk = atBasis(s.k[w.key]);
    const d = document.createElement('div');
    d.className = 'stat';
    d.innerHTML = `<div class="lab">${w.label}</div>
      <div class="val ${cls(v)}">${fmtPct(v)}</div>
      <div class="r">${rk != null ? 'rank ' + rk + (atBasis(s.N[w.key]) ? '/' + atBasis(s.N[w.key]) : '') : 'not ranked'}</div>`;
    stats.appendChild(d);
  });

  const dates = S.meta.dates;
  const nCut = S.span === '1Y' ? 53 : S.span === '3Y' ? 157 : dates.length;
  const from = Math.max(0, dates.length - nCut);

  const navPts = [];
  for (let i = from; i < dates.length; i++) navPts.push({ label: dates[i], v: ser.nav[i] });
  $('navSpanLabel').textContent = `${dates[from]} → ${dates[dates.length - 1]} · weekly closes`;
  drawChart($('navChart'), navPts, { color: '#5ac8b0', fill: true, fmt: fmtNav, unit: '₹' });

  // rank series on the selected basis
  const rDates = S.meta.rank_dates;
  const rFrom = Math.max(0, rDates.length - nCut);
  const arr = ser.h[S.win];
  const picked = [];
  let lastBucket = null;
  for (let i = rFrom; i < rDates.length; i++) {
    const key = bucketKey(rDates[i], S.basis);
    if (key !== lastBucket) { picked.push({ label: rDates[i], v: arr[i] }); lastBucket = key; }
    else { picked[picked.length - 1].v = arr[i]; picked[picked.length - 1].label = rDates[i]; }
  }
  const clean = picked.filter((p) => p.v !== null);
  const bestPossible = 1;
  const maxRank = Math.max(clean.reduce((a, p) => Math.max(a, p.v), 0), atBasis(s.N[S.win]) || 0, 2);
  $('rankSpanLabel').textContent = `${picked.length} ${S.basis} points · ${currentWindowLabel()} rank`;
  $('rankAxisNote').textContent = ' (rank 1 at top)';
  drawChart($('rankChart'), clean, {
    color: '#f2b24a', invert: true, minY: bestPossible, maxY: maxRank,
    fmt: (v) => '#' + Math.round(v), unit: '',
  });
}

function bucketKey(iso, basis) {
  if (basis === 'weekly') return iso;
  if (basis === 'monthly') return iso.slice(0, 7);
  const d = new Date(iso + 'T00:00:00');
  const y = d.getFullYear(), m = d.getMonth();
  if (basis === 'quarterly') return y + 'Q' + Math.floor(m / 3);
  if (basis === 'halfyearly') return y + (m < 6 ? 'H1' : 'H2');
  return String(y);
}

/* ---------------- tiny canvas chart ---------------- */
function drawChart(canvas, points, opts) {
  const dpr = window.devicePixelRatio || 1;
  // The CSS height is captured ONCE into data-h. Reading it back from the height
  // attribute was self-poisoning: we overwrite that attribute with the device-pixel
  // height, so every redraw (i.e. every mousemove) doubled the canvas and the chart
  // walked off the bottom of the screen.
  const cssH = +(canvas.dataset.h || canvas.getAttribute('height') || 220);
  if (!canvas.dataset.h) canvas.dataset.h = String(cssH);
  canvas.style.height = cssH + 'px';
  const cssW = Math.max(120, canvas.clientWidth || 420);
  const bw = Math.round(cssW * dpr), bh = Math.round(cssH * dpr);
  if (canvas.width !== bw || canvas.height !== bh) {
    canvas.width = bw;
    canvas.height = bh;
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const pad = { l: 46, r: 10, t: 10, b: 20 };
  const W = cssW - pad.l - pad.r, H = cssH - pad.t - pad.b;
  const vals = points.map((p) => p.v).filter((v) => v !== null);
  if (!vals.length) {
    ctx.fillStyle = '#8b97a8'; ctx.font = '12px sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('No data for this window', cssW / 2, cssH / 2);
    return;
  }
  let yMin = opts.minY !== undefined ? opts.minY : Math.min(...vals);
  let yMax = opts.maxY !== undefined ? opts.maxY : Math.max(...vals);
  if (yMin === yMax) { yMin -= 1; yMax += 1; }
  const span = yMax - yMin;
  yMin -= span * 0.05; yMax += span * 0.05;

  const xOf = (i) => pad.l + (points.length <= 1 ? W / 2 : (i / (points.length - 1)) * W);
  const yOf = (v) => {
    const t = (v - yMin) / (yMax - yMin);
    return pad.t + (opts.invert ? t * H : (1 - t) * H);
  };

  // grid + y labels
  ctx.font = '10px -apple-system,sans-serif'; ctx.textBaseline = 'middle';
  const ticks = 4;
  for (let i = 0; i <= ticks; i++) {
    const v = yMin + ((yMax - yMin) * i) / ticks;
    const y = yOf(v);
    ctx.strokeStyle = '#232b36'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pad.l, y + 0.5); ctx.lineTo(pad.l + W, y + 0.5); ctx.stroke();
    ctx.fillStyle = '#8b97a8'; ctx.textAlign = 'right';
    ctx.fillText(opts.fmt ? opts.fmt(v) : v.toFixed(1), pad.l - 6, y);
  }

  // x labels
  const nLab = Math.min(5, points.length);
  ctx.textAlign = 'center'; ctx.textBaseline = 'top'; ctx.fillStyle = '#8b97a8';
  for (let i = 0; i < nLab; i++) {
    const idx = Math.round((i / Math.max(1, nLab - 1)) * (points.length - 1));
    const lab = points[idx].label || '';
    const short = lab.length > 7 ? lab.slice(2) : lab;
    ctx.fillText(short, xOf(idx), pad.t + H + 5);
  }

  // area
  if (opts.fill) {
    const grad = ctx.createLinearGradient(0, pad.t, 0, pad.t + H);
    grad.addColorStop(0, 'rgba(90,200,176,.28)');
    grad.addColorStop(1, 'rgba(90,200,176,0)');
    ctx.beginPath();
    let started = false;
    points.forEach((p, i) => {
      if (p.v === null) return;
      if (!started) { ctx.moveTo(xOf(i), yOf(p.v)); started = true; }
      else ctx.lineTo(xOf(i), yOf(p.v));
    });
    const lastIdx = points.map((p) => p.v !== null).lastIndexOf(true);
    const firstIdx = points.map((p) => p.v !== null).indexOf(true);
    if (started) {
      ctx.lineTo(xOf(lastIdx), pad.t + H); ctx.lineTo(xOf(firstIdx), pad.t + H); ctx.closePath();
      ctx.fillStyle = grad; ctx.fill();
    }
  }

  // line
  ctx.beginPath(); let pen = false;
  points.forEach((p, i) => {
    if (p.v === null) { pen = false; return; }
    if (!pen) { ctx.moveTo(xOf(i), yOf(p.v)); pen = true; } else ctx.lineTo(xOf(i), yOf(p.v));
  });
  ctx.strokeStyle = opts.color; ctx.lineWidth = 1.8; ctx.lineJoin = 'round'; ctx.stroke();

  // last point dot
  const li = points.map((p) => p.v !== null).lastIndexOf(true);
  if (li >= 0) {
    ctx.beginPath(); ctx.arc(xOf(li), yOf(points[li].v), 2.6, 0, Math.PI * 2);
    ctx.fillStyle = opts.color; ctx.fill();
  }

  canvas._chart = { points, xOf, yOf, pad, W, H, opts, cssW, cssH };
  if (!canvas._wired) {
    canvas._wired = true;
    canvas.addEventListener('mousemove', (ev) => {
      const c = canvas._chart; if (!c) return;
      const r = canvas.getBoundingClientRect();
      const x = ev.clientX - r.left;
      if (x < c.pad.l || x > c.pad.l + c.W) { drawChart(canvas, c.points, c.opts); return; }
      const idx = Math.round(((x - c.pad.l) / c.W) * (c.points.length - 1));
      const p = c.points[idx]; if (!p || p.v === null) return;
      drawChart(canvas, c.points, c.opts);
      const ctx2 = canvas.getContext('2d');
      ctx2.save();
      ctx2.strokeStyle = '#3a4657'; ctx2.setLineDash([3, 3]);
      ctx2.beginPath(); ctx2.moveTo(c.xOf(idx), c.pad.t); ctx2.lineTo(c.xOf(idx), c.pad.t + c.H); ctx2.stroke();
      ctx2.restore();
      const txt = `${p.label}  ${c.opts.fmt ? c.opts.fmt(p.v) : p.v}`;
      ctx2.font = '11px -apple-system,sans-serif';
      const w = ctx2.measureText(txt).width + 12;
      let bx = c.xOf(idx) + 8; if (bx + w > c.cssW) bx = c.xOf(idx) - w - 8;
      ctx2.fillStyle = '#0b0f14'; ctx2.strokeStyle = '#2b3542';
      ctx2.beginPath(); ctx2.roundRect(bx, c.pad.t + 4, w, 20, 5); ctx2.fill(); ctx2.stroke();
      ctx2.fillStyle = '#e8edf4'; ctx2.textAlign = 'left'; ctx2.textBaseline = 'middle';
      ctx2.fillText(txt, bx + 6, c.pad.t + 14);
    });
  }
}

boot().catch((e) => {
  document.body.insertAdjacentHTML('beforeend',
    `<pre style="padding:20px;color:#ff6b6b">Failed to load data: ${e}</pre>`);
});
