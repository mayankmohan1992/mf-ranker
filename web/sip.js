/* SIP simulator — every number here is precomputed at build time by pipeline/sip.py.
   The browser does no NAV arithmetic: it only scales by the amount the user types,
   because XIRR is money-weighted and independent of the instalment size. */

let SIP_SEL = { si: 1, di: 1 };   // default: 3Y tenure, SIP day 5

function sipMeta() {
  return S.meta.sip || { starts: [1, 3, 5, 10], days: [1, 5, 10, 15, 25], amount: 1000 };
}

const money = (v) => '₹' + Math.round(v).toLocaleString('en-IN');

function sipAmount() {
  const el = $('sipAmt');
  const v = el ? Number(el.value) : 5000;
  return Number.isFinite(v) && v > 0 ? v : 5000;
}

function renderSip(scheme) {
  const s = scheme || (S.cat.schemes.find((x) => x.c === S.sel) || null);
  const grid = $('sipGrid');
  if (!grid) return;
  const meta = sipMeta();
  const data = s && s._series ? s._series.sip : null;

  if (!data) {
    grid.innerHTML = '<tbody><tr><td class="muted">No SIP data for this scheme.</td></tr></tbody>';
    $('sipResult').textContent = 'This scheme has too little NAV history to simulate a SIP.';
    return;
  }

  const med = (S.cat.sipm || {})[S.plan] || null;
  const unit = '';

  let h = '<thead><tr><th class="tl">SIP from</th>';
  meta.days.forEach((d) => { h += `<th class="num">day ${d}</th>`; });
  h += '<th class="num median">peer median</th></tr></thead><tbody>';

  meta.starts.forEach((yrs, si) => {
    h += `<tr><th class="tl">${yrs}Y</th>`;
    meta.days.forEach((d, di) => {
      const x = data.x[si][di];
      const v = data.v[si][di];
      const n = data.n[si][di];
      const f = (data.f && data.f[si][di]) || 0;
      const on = (si === SIP_SEL.si && di === SIP_SEL.di) ? ' on' : '';
      if (x === null || x === undefined) {
        const abs = v === null || v === undefined ? '—' : ((v / 1000 - 1) * 100).toFixed(1) + '%';
        const tip = n ? `${n} instalments · ${abs} absolute` : 'not enough history';
        h += `<td class="num na${on}" data-si="${si}" data-di="${di}" title="${tip}">${abs}</td>`;
      } else {
        const pct = (x / 10).toFixed(1);
        const cls = x >= 0 ? 'pos' : 'neg';
        const late = f > 45 ? ` · starts ${f}d late` : '';
        h += `<td class="num ${cls}${on}" data-si="${si}" data-di="${di}" `
           + `title="${n} instalments, ${((v / 1000 - 1) * 100).toFixed(1)}% absolute${late}">${pct}%</td>`;
      }
    });
    const m = med && med[si] ? med[si][SIP_SEL.di] : null;
    h += `<td class="num median">${m === null || m === undefined ? '—' : (m / 10).toFixed(1) + '%'}</td>`;
    h += '</tr>';
  });
  h += '</tbody>';
  grid.innerHTML = h;

  grid.querySelectorAll('td[data-si]').forEach((td) => {
    td.onclick = () => {
      SIP_SEL = { si: Number(td.dataset.si), di: Number(td.dataset.di) };
      renderSip(s);
    };
  });

  renderSipResult(s);
}

function renderSipResult(s) {
  const meta = sipMeta();
  const data = s && s._series ? s._series.sip : null;
  const out = $('sipResult');
  if (!out) return;
  if (!data) return;

  const si = SIP_SEL.si;
  const di = SIP_SEL.di;
  const yrs = meta.starts[si];
  const dom = meta.days[di];
  const x = data.x[si][di];
  const v = data.v[si][di];
  const n = data.n[si][di] || 0;
  const f = (data.f && data.f[si][di]) || 0;
  const amt = sipAmount();
  const invested = amt * n;
  const value = invested * (v === null || v === undefined ? 1 : v / 1000);
  const gain = value - invested;
  const absPct = invested > 0 ? (gain / invested) * 100 : 0;
  const med = ((S.cat.sipm || {})[S.plan] || [[null]])[si];
  const medX = med ? med[di] : null;

  let html = `<div class="siprow"><span class="k">${money(amt)}/month · ${yrs}Y · SIP day ${dom}</span>`;
  html += `<span>${n} instalments · invested <strong>${money(invested)}</strong></span>`;
  html += `<span>value <strong class="pos">${money(value)}</strong>`;
  html += ` <span class="${gain >= 0 ? 'pos' : 'neg'}">(${gain >= 0 ? '+' : ''}${money(gain)}, ${absPct.toFixed(1)}%)</span></span>`;
  if (x !== null && x !== undefined) {
    html += `<span>XIRR <strong class="pos">${(x / 10).toFixed(2)}%</strong></span>`;
    if (medX !== null && medX !== undefined) {
      const better = x >= medX;
      html += `<span class="muted">peer median ${(medX / 10).toFixed(2)}% `
            + `<span class="${better ? 'pos' : 'neg'}">(${better ? 'ahead' : 'behind'} by `
            + `${Math.abs(x / 10 - medX / 10).toFixed(2)}pp)</span></span>`;
    }
  } else {
    html += '<span class="muted">XIRR n/a — window too short to annualise</span>';
  }
  html += '</div>';

  if (f > 45) {
    const days = (S.meta.dates || []).length ? '' : '';
    html += `<div class="warn small">Fund history begins ${f} days after this window opened, so this is `
          + `not a full ${yrs}-year SIP — only ${n} instalments were possible.${days}</div>`;
  }
  out.innerHTML = html;
}
