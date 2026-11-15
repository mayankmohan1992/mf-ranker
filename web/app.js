/* MF Ranker — vanilla single page, no dependencies.
   Data: static JSON produced by pipeline/compute.py from AMFI NAV files. */

const S = {
  meta: null, cats: [], slug: null, cat: null,
  plan: 'Direct', win: '1Y', basis: 'weekly', dir: 'top', n: 20,
  sort: 'ret', sortDesc: true, span: '1Y', sel: null, search: '',
  series: {},
};

const $ = (id) => document.getElementById(id);
const fmtPct = (v) => (v === null || v === undefined) ? '—' : (v > 0 ? '+' : '') + v.toFixed(2) + '%';
const cls = (v) => v === null || v === undefined ? 'muted' : (v > 0 ? 'pos' : v < 0 ? 'neg' : 'muted');
const fmtNav = (v) => v === null || v === undefined ? '—' : v.toFixed(2);

/* ---------------- boot ---------------- */
async function boot() {
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

  buildCatNav();
  const preferred = S.meta.categories.find((c) => c.slug === 'large-cap-fund')
    || S.meta.categories.slice().sort((a, b) => b.count - a.count)[0];
  if (preferred) await selectCat(preferred.slug);

  win.onchange = () => { S.win = win.value; render(); };
  $('basis').onchange = (e) => { S.basis = e.target.value; if (S.sel) drawDetail(); };
  $('dir').onchange = (e) => { S.dir = e.target.value; S.sort = 'ret'; render(); };
  $('n').onchange = (e) => { S.n = Math.max(1, Math.min(500, +e.target.value || 20)); render(); };
  $('search').oninput = (e) => { S.search = e.target.value.toLowerCase().trim(); render(); };
  $('planSeg').onclick = (e) => {
    const b = e.target.closest('button'); if (!b) return;
    [...$('planSeg').children].forEach((x) => x.classList.toggle('on', x === b));
    S.plan = b.dataset.plan; S.sel = null; $('detail').hidden = true; render();
  };
  $('spanSeg').onclick = (e) => {
    const b = e.target.closest('button'); if (!b) return;
    [...$('spanSeg').children].forEach((x) => x.classList.toggle('on', x === b));
    S.span = b.dataset.span; if (S.sel) drawDetail();
  };
  document.querySelectorAll('th.sortable').forEach((th) => {
    th.onclick = () => {
      const key = th.dataset.sort;
      if (S.sort === key) S.sortDesc = !S.sortDesc; else { S.sort = key; S.sortDesc = key !== 'name'; }
      render();
    };
  });
  window.addEventListener('resize', () => { if (S.sel) drawDetail(); });
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
  S.sel = null; $('detail').hidden = true;
  render();
}

/* ---------------- table ---------------- */
function currentWindowLabel() {
  const w = S.meta.windows.find((x) => x.key === S.win);
  return w ? w.label : S.win;
}

function rankOf(s) { const r = s.k[S.win]; return r === null || r === undefined ? null : r; }

function render() {
  if (!S.cat) return;
  $('catTitle').textContent = S.cat.name;
  const planTotal = S.cat.schemes.filter((s) => s.p === S.plan).length;
  $('catMeta').innerHTML = `${S.cat.asset} · ${planTotal} ${S.plan} growth schemes `
    + `· ranked by ${currentWindowLabel()} return `
    + `${S.cat.schemes.some((s) => s.g) ? '· index/theme funds ranked within their own benchmark' : ''}`;
  $('thRet').textContent = currentWindowLabel();
  $('ctxHint').textContent = `Showing ${S.dir === 'top' ? 'top' : 'bottom'} ${S.n} of ${planTotal}`
    + (S.dir === 'top' ? '' : ' — worst first');

  let rows = S.cat.schemes.filter((s) => s.p === S.plan);
  if (S.search) rows = rows.filter((s) => s.n.toLowerCase().includes(S.search));
  rows = rows.filter((s) => s.r[S.win] !== null);
  rows.sort((a, b) => {
    const pick = (s) => S.sort === 'name' ? s.n.toLowerCase() : S.sort === 'amc' ? (s.a || '').toLowerCase()
      : S.sort === 'rank' ? (rankOf(s) ?? 1e9)
        : (S.sort === 'ret' ? s.r[S.win] : s.n.toLowerCase());
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
    const dv = s.d[S.win];                            // positive = improved (rank number fell)
    let delta = '<span class="muted">—</span>';
    if (dv !== null && dv !== undefined && dv !== 0) {
      delta = `<span class="${dv > 0 ? 'pos' : 'neg'}">${dv > 0 ? '▲' : '▼'} ${Math.abs(dv)}</span>`;
    }

    const tr = document.createElement('tr');
    if (S.sel === s.c) tr.className = 'on';
    tr.innerHTML = `
      <td class="num muted">${i + 1}</td>
      <td class="name"><b>${s.n}</b>${s.g ? `<span class="tag">${s.g}</span>` : ''}</td>
      <td class="muted">${s.a || '—'}</td>
      <td class="num ${cls(s.r[S.win])}">${fmtPct(s.r[S.win])}</td>
      <td class="num"><span class="rankpill">${rk ?? '—'}${rk !== null && s.N[S.win] ? ' / ' + s.N[S.win] : ''}</span></td>
      <td class="num">${delta}</td>`;
    tr.onclick = () => { S.sel = s.c; render(); openDetail(s); };
    tb.appendChild(tr);
  });
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
  S.series[code] = { nav, h };
  return S.series[code];
}

async function openDetail(scheme) {
  const s = scheme || S.cat.schemes.find((x) => x.c === S.sel);
  if (!s) return;
  $('detail').hidden = false;
  $('dName').textContent = s.n;
  $('dMeta').innerHTML = `${s.a || '—'}${s.g ? ' · ' + s.g : ''} · ${S.plan} plan · ${S.cat.name}`;
  $('dStats').innerHTML = '<div class="stat"><div class="lab">loading</div><div class="val muted">…</div></div>';
  try {
    s._series = await loadSeries(s.c);
  } catch (e) {
    $('dStats').innerHTML = '<div class="stat"><div class="lab">error</div><div class="val neg">series unavailable</div></div>';
    return;
  }
  if (S.sel === s.c) drawDetail(s);
}

function drawDetail(scheme) {
  const s = scheme || (S.cat.schemes.find((x) => x.c === S.sel) || null);
  if (!s || !s._series) return;
  const ser = s._series;
  $('detail').hidden = false;
  $('dName').textContent = s.n;
  $('dMeta').innerHTML = `${s.a || '—'}${s.g ? ' · ' + s.g : ''} · ${S.plan} plan · `
    + `${S.cat.name} · ${S.cat.asset}`;

  const stats = $('dStats');
  stats.innerHTML = '';
  S.meta.windows.forEach((w) => {
    const v = s.r[w.key];
    const rk = s.k[w.key];
    const d = document.createElement('div');
    d.className = 'stat';
    d.innerHTML = `<div class="lab">${w.label}</div>
      <div class="val ${cls(v)}">${fmtPct(v)}</div>
      <div class="r">${rk !== null ? 'rank ' + rk + (s.N[w.key] ? '/' + s.N[w.key] : '') : 'not ranked'}</div>`;
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
  const maxRank = Math.max(clean.reduce((a, p) => Math.max(a, p.v), 0), s.N[S.win] || 0, 2);
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
  const cssW = canvas.clientWidth || 420;
  const cssH = +canvas.getAttribute('height') || 220;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
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
