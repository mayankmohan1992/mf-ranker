/* Compare up to 20 schemes: growth chart, summary, calendar years, correlation.
   Everything is derived from the same static JSON the ranking table uses. */

const MAX_CMP = 20;
const CAT_CACHE = {};
let CMP_ROWS = [];
const CMP_HIDDEN = new Set();

const PALETTE = ['#4c9aff', '#f2b24a', '#5ad18a', '#e2646c', '#a78bfa', '#38bdf8',
  '#f472b6', '#facc15', '#34d399', '#fb923c', '#818cf8', '#22d3ee',
  '#a3e635', '#f87171', '#c084fc', '#2dd4bf', '#fdba74', '#93c5fd',
  '#fda4af', '#bef264'];

function catSlug(code) {
  const hit = (S.lookup || []).find((x) => x[0] === code);
  return (hit && hit[2]) || S.slug;
}

function toast(msg) {
  let el = document.getElementById('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    el.className = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add('on');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('on'), 2200);
}

function toggleCmp(code, on) {
  if (on) {
    if (S.cmp.includes(code)) return;
    if (S.cmp.length >= MAX_CMP) { toast(`Up to ${MAX_CMP} schemes can be compared`); render(); return; }
    S.cmp.push(code);
  } else {
    S.cmp = S.cmp.filter((c) => c !== code);
  }
  updateTray();
  render();
}

function updateTray() {
  const tray = $('tray');
  if (!tray) return;
  const n = S.cmp.length;
  tray.hidden = n === 0 || S.cmpOpen;
  $('trayCount').textContent = `${n} selected`;
  $('trayHint').textContent = n >= MAX_CMP ? `limit reached (${MAX_CMP})` : `up to ${MAX_CMP} can be compared`;
  $('btnCompare').disabled = n < 2;
  $('btnCompare').title = n < 2 ? 'Select at least two schemes' : `Compare ${n} schemes`;
}

async function ensureLookup() {
  if (!S.lookup) S.lookup = await (await fetch('data/lookup.json')).json();
  return S.lookup;
}

async function schemeRow(code) {
  if (S.cat) {
    const hit = S.cat.schemes.find((s) => s.c === code);
    if (hit) return hit;
  }
  const lookup = await ensureLookup();
  const entry = lookup.find((r) => r[0] === code);
  if (!entry) return null;
  const slug = entry[2];
  if (!CAT_CACHE[slug]) {
    CAT_CACHE[slug] = await (await fetch(`data/cat/${slug}.json`)).json();
  }
  return (CAT_CACHE[slug].schemes || []).find((s) => s.c === code) || null;
}

async function openCompare() {
  if (S.cmp.length < 2) return;
  S.cmpOpen = true;
  const view = $('cmpView');
  $('rankCard').hidden = true;
  $('tray').hidden = true;
  view.hidden = false;
  $('cmpTitle').textContent = 'Comparing';
  $('cmpMeta').textContent = 'loading…';
  $('cmpWarn').hidden = true;

  // lookup carries the category slug for codes outside the current table
  await ensureLookup();

  // rows first, so we can label the view even while series load
  const rows = [];
  for (const code of S.cmp.slice()) {
    const r = await schemeRow(code);
    if (r) rows.push(r);
  }
  CMP_ROWS = rows;
  CMP_HIDDEN.clear();

  const series = await Promise.all(rows.map(async (r) => {
    try { return await loadSeries(r.c); } catch (e) { return null; }
  }));
  rows.forEach((r, i) => { r._series = series[i]; });

  const plans = [...new Set(rows.map((r) => r.p))];
  const cats = [...new Set(rows.map((r) => ((S.lookup || []).find((x) => x[0] === r.c) || [])[2] || S.slug))];
  const warn = [];
  if (plans.length > 1) warn.push(`mixing ${plans.join(' and ')} plans`);
  if (cats.length > 1) warn.push(`${cats.length} categories — ranks are only comparable inside a category`);
  if (warn.length) {
    $('cmpWarn').hidden = false;
    $('cmpWarn').textContent = 'Heads up: ' + warn.join(' · ') + '.';
  }

  const dates = S.meta.dates;
  const firsts = rows.map((r) => {
    const nav = r._series ? r._series.nav : [];
    const i = nav.findIndex((v) => v !== null);
    return i < 0 ? dates.length - 1 : i;
  });
  const startIdx = Math.max(...firsts);
  const endIdx = dates.length - 1;
  $('cmpSpan').textContent = startIdx < endIdx
    ? `${dates[startIdx]} → ${dates[endIdx]} · common window`
    : 'not enough overlap';
  $('cmpMeta').textContent = `${rows.length} schemes · ${dates[startIdx]} → ${dates[endIdx]}`;

  drawCompareChart(rows, startIdx, endIdx);
  buildSummary(rows);
  buildCalendar(rows);
  buildCorrelation(rows, startIdx, endIdx);
  updateTray();
}

function closeCompare() {
  S.cmpOpen = false;
  $('cmpView').hidden = true;
  $('rankCard').hidden = false;
  updateTray();
  render();
}

function growth(row, startIdx, endIdx) {
  const nav = row._series ? row._series.nav : null;
  if (!nav) return null;
  const base = nav[startIdx];
  if (!base) return null;
  const pts = [];
  let missing = 0;
  for (let i = startIdx; i <= endIdx; i++) {
    const v = nav[i];
    if (v === null || v === undefined) { missing++; pts.push({ label: S.meta.dates[i], v: null }); }
    else pts.push({ label: S.meta.dates[i], v: (v / base) * 10000 });
  }
  return { pts, missing, coverage: 1 - missing / Math.max(1, pts.length) };
}

function drawCompareChart(rows, startIdx, endIdx) {
  const canvas = $('cmpChart');
  const lines = [];
  rows.forEach((r, i) => {
    const g = growth(r, startIdx, endIdx);
    if (!g) return;
    lines.push({ name: r.n, color: PALETTE[i % PALETTE.length], pts: g.pts, code: r.c, coverage: g.coverage });
  });
  drawMulti(canvas, lines.filter((l) => !CMP_HIDDEN.has(l.code)));

  const legend = $('cmpLegend');
  legend.innerHTML = '';
  lines.forEach((l) => {
    const b = document.createElement('button');
    b.className = 'chip' + (CMP_HIDDEN.has(l.code) ? ' off' : '');
    b.innerHTML = `<i style="background:${l.color}"></i>${l.name}`;
    b.onclick = () => {
      if (CMP_HIDDEN.has(l.code)) CMP_HIDDEN.delete(l.code); else CMP_HIDDEN.add(l.code);
      drawCompareChart(CMP_ROWS, startIdx, endIdx);
    };
    legend.appendChild(b);
  });
}

function drawMulti(canvas, lines) {
  const dpr = window.devicePixelRatio || 1;
  const cssH = +(canvas.dataset.h || canvas.getAttribute('height') || 320);
  if (!canvas.dataset.h) canvas.dataset.h = String(cssH);
  canvas.style.height = cssH + 'px';
  const cssW = Math.max(200, canvas.clientWidth || 600);
  const bw = Math.round(cssW * dpr), bh = Math.round(cssH * dpr);
  if (canvas.width !== bw || canvas.height !== bh) { canvas.width = bw; canvas.height = bh; }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const pad = { l: 58, r: 12, t: 12, b: 24 };
  const W = cssW - pad.l - pad.r, H = cssH - pad.t - pad.b;
  const vals = [];
  lines.forEach((l) => l.pts.forEach((p) => { if (p.v !== null) vals.push(p.v); }));
  if (!vals.length) {
    ctx.fillStyle = '#8b97a8'; ctx.font = '12px sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('No overlapping data', cssW / 2, cssH / 2);
    return;
  }
  let yMin = Math.min(...vals), yMax = Math.max(...vals);
  const padY = (yMax - yMin) * 0.06 || 100;
  yMin -= padY; yMax += padY;
  const n = lines[0].pts.length;
  const xOf = (i) => pad.l + (n <= 1 ? W / 2 : (i / (n - 1)) * W);
  const yOf = (v) => pad.t + (1 - (v - yMin) / (yMax - yMin)) * H;

  ctx.font = '10px -apple-system,sans-serif'; ctx.textBaseline = 'middle';
  for (let t = 0; t <= 4; t++) {
    const v = yMin + ((yMax - yMin) * t) / 4;
    const y = yOf(v);
    ctx.strokeStyle = 'rgba(255,255,255,.07)'; ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + W, y); ctx.stroke();
    ctx.fillStyle = '#8b97a8'; ctx.textAlign = 'right';
    ctx.fillText(Math.round(v).toLocaleString('en-IN'), pad.l - 6, y);
  }
  const step = Math.max(1, Math.floor(n / 5));
  ctx.textAlign = 'center'; ctx.textBaseline = 'top';
  for (let i = 0; i < n; i += step) {
    ctx.fillStyle = '#8b97a8';
    ctx.fillText(lines[0].pts[i].label.slice(0, 7), xOf(i), cssH - pad.b + 6);
  }

  lines.forEach((l) => {
    ctx.strokeStyle = l.color; ctx.lineWidth = 1.6; ctx.beginPath();
    let started = false;
    l.pts.forEach((p, i) => {
      if (p.v === null) { started = false; return; }
      const x = xOf(i), y = yOf(p.v);
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });
}

function buildSummary(rows) {
  const t = $('cmpTable');
  const W = S.meta.windows;
  let h = '<thead><tr><th class="tl">Scheme</th><th>Cat</th>';
  W.forEach((w) => { h += `<th class="num">${w.label}</th>`; });
  h += '<th class="num">SIP 5Y</th></tr></thead><tbody>';
  rows.forEach((r) => {
    const sip = r._series && r._series.sip ? r._series.sip.x[2][1] : null;
    h += `<tr><td class="tl">${r.n}<div class="muted tiny">${r.a || ''} · ${r.p}</div></td>`;
    h += `<td class="muted">${catSlug(r.c)}</td>`;
    W.forEach((w) => {
      const v = r.r[w.key];
      h += `<td class="num ${cls(v)}">${fmtPct(v)}</td>`;
    });
    h += `<td class="num ${sip === null || sip === undefined ? 'muted' : 'pos'}">`
       + `${sip === null || sip === undefined ? '—' : (sip / 10).toFixed(1) + '%'}</td></tr>`;
  });
  h += '</tbody>';
  t.innerHTML = h;
}

function buildCalendar(rows) {
  const t = $('cmpCal');
  const years = [...new Set(rows.flatMap((r) => Object.keys((r._series && r._series.cy) || {})))]
    .map(Number).sort();
  if (!years.length) { t.innerHTML = '<tbody><tr><td class="muted">no data</td></tr></tbody>'; return; }
  let h = '<thead><tr><th class="tl">Scheme</th>';
  years.forEach((y) => { h += `<th class="num">${String(y).slice(2)}</th>`; });
  h += '</tr></thead><tbody>';
  rows.forEach((r) => {
    const cy = (r._series && r._series.cy) || {};
    h += `<tr><td class="tl">${r.n.slice(0, 26)}</td>`;
    years.forEach((y) => {
      const v = cy[y];
      h += `<td class="num ${cls(v)}">${v === undefined ? '—' : v.toFixed(1)}</td>`;
    });
    h += '</tr>';
  });
  t.innerHTML = h + '</tbody>';
}

function weeklyReturns(ser, startIdx, endIdx) {
  const out = [];
  for (let i = startIdx + 1; i <= endIdx; i++) {
    const a = ser.nav[i - 1], b = ser.nav[i];
    if (a && b) out.push({ i, r: b / a - 1 });
  }
  return out;
}

function buildCorrelation(rows, startIdx, endIdx) {
  const t = $('cmpCorr');
  const rets = rows.map((r) => (r._series ? weeklyReturns(r._series, startIdx, endIdx) : []));
  const map = rets.map((arr) => new Map(arr.map((x) => [x.i, x.r])));
  const corr = (a, b) => {
    const xs = [], ys = [];
    map[a].forEach((v, k) => { if (map[b].has(k)) { xs.push(v); ys.push(map[b].get(k)); } });
    if (xs.length < 10) return null;
    const mx = xs.reduce((s, v) => s + v, 0) / xs.length;
    const my = ys.reduce((s, v) => s + v, 0) / ys.length;
    let num = 0, dx = 0, dy = 0;
    for (let i = 0; i < xs.length; i++) {
      num += (xs[i] - mx) * (ys[i] - my);
      dx += (xs[i] - mx) ** 2; dy += (ys[i] - my) ** 2;
    }
    return dx && dy ? num / Math.sqrt(dx * dy) : null;
  };
  let h = '<thead><tr><th class="tl"></th>';
  rows.forEach((r) => { h += `<th class="num" title="${r.n}">${r.n.slice(0, 2)}</th>`; });
  h += '</tr></thead><tbody>';
  rows.forEach((r, i) => {
    h += `<tr><td class="tl">${r.n.slice(0, 22)}</td>`;
    rows.forEach((_, j) => {
      const c = i === j ? 1 : corr(i, j);
      if (c === null) { h += '<td class="num muted">—</td>'; return; }
      const op = Math.max(0, Math.min(1, Math.abs(c)));
      h += `<td class="num" style="background:rgba(76,154,255,${(op * 0.55).toFixed(2)})">${c.toFixed(2)}</td>`;
    });
    h += '</tr>';
  });
  t.innerHTML = h + '</tbody>';
}

function compareCsv() {
  const W = S.meta.windows;
  const head = ['Scheme', 'Fund house', 'Plan', 'Category', ...W.map((w) => w.label), 'SIP 5Y XIRR %'];
  const lines = [head.join(',')];
  CMP_ROWS.forEach((r) => {
    const sip = r._series && r._series.sip ? (r._series.sip.x[2][1] / 10).toFixed(2) : '';
    const cat = catSlug(r.c);
    const cells = [r.n, r.a || '', r.p, cat, ...W.map((w) => (r.r[w.key] === null ? '' : r.r[w.key])), sip];
    lines.push(cells.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(','));
  });
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `mf-compare-${S.meta.as_of}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
  toast('CSV exported');
}

function shareLink() {
  const p = new URLSearchParams();
  p.set('cat', S.slug);
  p.set('win', S.win);
  p.set('basis', S.basis);
  p.set('dir', S.dir);
  p.set('plan', S.plan);
  p.set('n', String(S.n));
  if (S.cmp.length) p.set('cmp', S.cmp.join(','));
  const url = location.origin + location.pathname + '?' + p.toString();
  copyText(url);
  return url;
}

/* Copy without blocking the page: prompt() freezes the UI (and blocks automation),
   and navigator.clipboard is unavailable on plain http. Fall back to a hidden
   textarea + execCommand, and always show the link in the toast so it can be read. */
function copyText(text) {
  const fallback = () => {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;top:-1000px;opacity:0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) { /* ignore */ }
    document.body.removeChild(ta);
    toast('Link copied · ' + text.slice(-48));
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(() => toast('Link copied'), fallback);
  } else {
    fallback();
  }
}
