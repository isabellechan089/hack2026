// Small inline-SVG chart primitives.
//
// Shared rules, applied by every primitive here:
//  * every plot carries a labelled scale, so a bar's length can be read as a
//    number rather than only compared to its neighbour,
//  * geometry is in pixel-like viewBox units with the default
//    preserveAspectRatio, so glyphs are never stretched and the chart's height
//    follows from its content instead of from the width of its container,
//  * data ends are rounded 4px and anchored to the baseline; lines are 2px,
//  * touching fills are separated by a 2px gap in the surface colour rather
//    than by a stroke, so the separation reads at any zoom,
//  * text wears ink tokens, never the series colour -- a colour chip beside a
//    label carries identity instead,
//  * grid and axes are recessive, and values are direct-labelled rather than
//    printed on every mark,
//  * every mark carries a <title>, so hovering gives the underlying numbers.
//
// The exposure hues were checked with the palette validator: the previous
// orange/yellow pair sat at deltaE 8.8 under normal vision, under the floor of
// 15, so downstream moved to a cool hue.

const CH = {
  esc: s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  pct: v => v == null ? '--' : (v * 100).toFixed(0) + '%',
  num: (v, d = 2) => v == null || Number.isNaN(v) ? '--' : Number(v).toFixed(d),
  int: v => v == null ? '--' : Number(v).toLocaleString(),
};

// The drawing width every primitive works in. Height comes from the content,
// so the rendered aspect ratio is set here rather than by the container.
const CW = 800;

/** Round numbers for an axis that starts at zero: 1, 2, 2.5 or 5 x 10^n. */
function niceTicks(max, count = 4) {
  if (!(max > 0)) return [0];
  const raw = max / count, power = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].find(m => m * power >= raw) * power;
  const out = [];
  for (let v = 0; v <= max + step * 0.001; v += step) out.push(Number(v.toPrecision(12)));
  return out;
}

/** Horizontal bars against a labelled scale. rows: [{label, value, display, color?, note?}] */
function hbar(rows, opts = {}) {
  const isShare = opts.max === 1;
  const raw = opts.max ?? Math.max(...rows.map(r => r.value || 0), 1e-9);
  const ticks = isShare ? [0, 0.25, 0.5, 0.75, 1] : niceTicks(raw);
  // The scale ends on a tick, so the longest bar never runs past the axis.
  const max = Math.max(raw, ticks[ticks.length - 1]);
  const rowH = 30, barH = 16, axisH = 30, top = 4;
  const h = rows.length * rowH + axisH + top;
  const baseline = top + rows.length * rowH;
  const X = v => Math.max(0, Math.min(1, (v || 0) / max)) * CW;
  const fmt = v => isShare ? CH.pct(v) : CH.int(v);

  let out = `<svg class="chart" viewBox="0 0 ${CW} ${h}" role="img" aria-label="${CH.esc(opts.title || 'bar chart')}">`;
  // Gridlines first, so the bars paint over them.
  for (const t of ticks) {
    out += `<line x1="${X(t).toFixed(1)}" y1="${top}" x2="${X(t).toFixed(1)}" y2="${baseline}" stroke="${VIZ.grid}" stroke-width="1"/>`;
  }
  rows.forEach((r, i) => {
    const y = top + i * rowH + (rowH - barH) / 2;
    const len = Math.max(2, X(r.value));
    out += `<g><title>${CH.esc(r.label)}: ${CH.esc(r.display ?? r.value)}${r.note ? ' — ' + CH.esc(r.note) : ''}</title>`
      + `<rect x="0" y="${top + i * rowH}" width="${CW}" height="${rowH}" fill="transparent"/>`
      + `<rect x="0" y="${y}" width="${len.toFixed(1)}" height="${barH}" rx="4" fill="${r.color || VIZ.accent}"/></g>`;
  });
  out += `<line x1="0" y1="${baseline}" x2="${CW}" y2="${baseline}" stroke="${VIZ.grid}" stroke-width="1.5"/>`;
  ticks.forEach((t, i) => {
    const anchor = i === 0 ? 'start' : i === ticks.length - 1 ? 'end' : 'middle';
    out += `<text x="${X(t).toFixed(1)}" y="${baseline + 19}" font-size="15" fill="${VIZ.muted}" text-anchor="${anchor}">${CH.esc(fmt(t))}</text>`;
  });
  out += '</svg><div class="chartlabels">';
  rows.forEach(r => {
    out += `<div class="chartrow"><span class="chip" style="background:${r.color || VIZ.accent}"></span>`
      + `<span class="rowlabel">${CH.esc(r.label)}</span>`
      + `<b>${CH.esc(r.display ?? r.value)}</b>`
      + (r.note ? `<span class="rownote">${CH.esc(r.note)}</span>` : '') + '</div>';
  });
  return out + '</div>';
}

/** One stacked part-to-whole bar. segments: [{label, value, color, note}] */
function stackbar(segments, opts = {}) {
  const total = segments.reduce((a, s) => a + (s.value || 0), 0) || 1;
  const gap = 0.6;                       // the 2px surface gap, in viewBox units
  let x = 0, out = `<svg class="chart stack" viewBox="0 0 100 16" role="img" aria-label="${CH.esc(opts.title || 'composition')}" preserveAspectRatio="none">`;
  segments.forEach((s, i) => {
    const raw = (s.value || 0) / total * 100;
    const wide = Math.max(0, raw - (i < segments.length - 1 ? gap : 0));
    out += `<g><title>${CH.esc(s.label)}: ${CH.int(s.value)} of ${CH.int(total)} (${CH.pct(s.value / total)})</title>`
      + `<rect x="${x}" y="0" width="${wide}" height="16" rx="2" fill="${s.color}"/></g>`;
    x += raw;
  });
  out += '</svg><div class="chartlabels">';
  segments.forEach(s => {
    out += `<div class="chartrow"><span class="chip" style="background:${s.color}"></span>`
      + `<span class="rowlabel">${CH.esc(s.label)}</span><b>${CH.int(s.value)}</b>`
      + `<span class="rownote">${CH.pct(s.value / total)}${s.note ? ' · ' + CH.esc(s.note) : ''}</span></div>`;
  });
  return out + '</div>';
}

/** Forest plot on a log hazard-ratio scale. rows: [{label, value, lo, hi, color, k, sub}] */
function forest(rows, opts = {}) {
  const usable = rows.filter(r => r.value);
  if (!usable.length) return '<p class="empty">No poolable estimate for this cohort.</p>';
  const lo = Math.min(...usable.map(r => r.lo ?? r.value), 1) * 0.92;
  const hi = Math.max(...usable.map(r => r.hi ?? r.value), 1) * 1.08;
  const L = Math.log(lo), H = Math.log(hi);
  const pad = 26;                        // room for the end tick labels
  const X = v => pad + (Math.log(v) - L) / (H - L) * (CW - pad * 2);
  const rowH = 42, axisH = 32, top = 8;
  const h = rows.length * rowH + axisH + top;
  const baseline = top + rows.length * rowH;

  // Ticks at hazard ratios a reader recognises, thinned to at most six.
  const candidates = [0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 2, 2.5];
  let ticks = candidates.filter(t => t >= lo && t <= hi);
  while (ticks.length > 6) ticks = ticks.filter((t, i) => t === 1 || i % 2 === 0);
  if (!ticks.length) ticks = [lo, hi];

  let out = `<svg class="chart forest" viewBox="0 0 ${CW} ${h}" role="img" aria-label="${CH.esc(opts.title || 'pooled effect estimates')}">`;
  for (const t of ticks) {
    const isNull = t === 1;
    out += `<line x1="${X(t).toFixed(1)}" y1="${top}" x2="${X(t).toFixed(1)}" y2="${baseline}" stroke="${isNull ? VIZ.muted : VIZ.grid}" stroke-width="${isNull ? 1.5 : 1}"${isNull ? ' stroke-dasharray="4 4"' : ''}/>`;
  }
  rows.forEach((r, i) => {
    if (!r.value) return;
    const y = top + i * rowH + rowH / 2, c = r.color || VIZ.accent;
    if (r.lo && r.hi) {
      out += `<line x1="${X(r.lo).toFixed(1)}" y1="${y}" x2="${X(r.hi).toFixed(1)}" y2="${y}" stroke="${c}" stroke-width="3" stroke-linecap="round"/>`
        + `<line x1="${X(r.lo).toFixed(1)}" y1="${y - 6}" x2="${X(r.lo).toFixed(1)}" y2="${y + 6}" stroke="${c}" stroke-width="2"/>`
        + `<line x1="${X(r.hi).toFixed(1)}" y1="${y - 6}" x2="${X(r.hi).toFixed(1)}" y2="${y + 6}" stroke="${c}" stroke-width="2"/>`;
    }
    out += `<g><title>${CH.esc(r.label)}: HR ${CH.num(r.value, 3)}${r.lo ? ` (95% CI ${CH.num(r.lo, 3)}–${CH.num(r.hi, 3)})` : ''}${r.k ? `, ${r.k} trials` : ''}</title>`
      + `<circle cx="${X(r.value).toFixed(1)}" cy="${y}" r="7" fill="${c}" stroke="${VIZ.surface}" stroke-width="2"/></g>`;
  });
  out += `<line x1="0" y1="${baseline}" x2="${CW}" y2="${baseline}" stroke="${VIZ.grid}" stroke-width="1.5"/>`;
  ticks.forEach(t => {
    out += `<text x="${X(t).toFixed(1)}" y="${baseline + 19}" font-size="15" fill="${t === 1 ? VIZ.ink : VIZ.muted}" text-anchor="middle">${t === 1 ? '1.0' : CH.num(t, t < 1 ? 2 : 2)}</text>`;
  });
  out += `<text x="0" y="${h - 1}" font-size="13" fill="${VIZ.muted}">← larger treatment effect</text>`
    + `<text x="${CW}" y="${h - 1}" font-size="13" fill="${VIZ.muted}" text-anchor="end">no difference at HR 1.0 →</text></svg>`;
  out += '<div class="chartlabels">';
  rows.forEach(r => {
    out += `<div class="chartrow"><span class="chip" style="background:${r.color || VIZ.accent}"></span>`
      + `<span class="rowlabel">${CH.esc(r.label)}</span>`
      + `<b>${r.value ? 'HR ' + CH.num(r.value, 3) : '--'}</b>`
      + `<span class="rownote">${r.lo ? `95% CI ${CH.num(r.lo, 3)}–${CH.num(r.hi, 3)} · ` : ''}${r.sub || ''}</span></div>`;
  });
  return out + '</div>';
}

/** A single ratio against a limit. */
function meter(value, target, label, note) {
  const pct = Math.max(0, Math.min(1, (value || 0)));
  const short = target != null && value < target;
  const color = short ? (value < target * 0.7 ? VIZ.accent : '#c2913c') : VIZ.good;
  return `<div class="meter"><div class="meterhead"><span>${CH.esc(label)}</span><b style="color:${color}">${CH.pct(value)}</b></div>`
    + `<div class="metertrack"><div class="meterfill" style="width:${pct * 100}%;background:${color}"></div>`
    + (target != null ? `<div class="metermark" style="left:${target * 100}%" title="target ${CH.pct(target)}"></div>` : '')
    + `</div>${note ? `<span class="rownote">${CH.esc(note)}</span>` : ''}</div>`;
}

/** A single line over an ordered x, with a labelled y scale. points: [{y, label}] */
function linechart(points, opts = {}) {
  const ys = points.map(p => p.y).filter(v => v != null);
  if (ys.length < 2) return '';
  const ymin = Math.min(...ys), ymax = Math.max(...ys), span = (ymax - ymin) || 1;
  const padL = 56, padR = 16, padT = 14, padB = 34, plotH = 150;
  const h = plotH + padT + padB;
  const X = i => padL + i / (points.length - 1) * (CW - padL - padR);
  const Y = v => padT + plotH - (v - ymin) / span * plotH;
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(p.y).toFixed(1)}`).join(' ');
  const gridY = [ymin, ymin + span / 2, ymax];

  let out = `<svg class="chart line" viewBox="0 0 ${CW} ${h}" role="img" aria-label="${CH.esc(opts.title || 'sensitivity')}">`;
  for (const v of gridY) {
    out += `<line x1="${padL}" y1="${Y(v).toFixed(1)}" x2="${CW - padR}" y2="${Y(v).toFixed(1)}" stroke="${VIZ.grid}" stroke-width="1"/>`
      + `<text x="${padL - 8}" y="${(Y(v) + 5).toFixed(1)}" font-size="15" fill="${VIZ.muted}" text-anchor="end">${CH.num(v, 2)}</text>`;
  }
  out += `<path d="${path}" fill="none" stroke="${VIZ.accent}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
  points.forEach((p, i) => {
    out += `<g><title>${CH.esc(p.label)}</title>`
      + `<rect x="${(X(i) - 14).toFixed(1)}" y="${padT}" width="28" height="${plotH}" fill="transparent"/>`
      + `<circle cx="${X(i).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="5" fill="${VIZ.accent}" stroke="${VIZ.surface}" stroke-width="2"/></g>`;
  });
  return out + `<text x="${padL}" y="${h - 12}" font-size="15" fill="${VIZ.muted}">${CH.esc(opts.xlo || '')}</text>`
    + `<text x="${CW - padR}" y="${h - 12}" font-size="15" fill="${VIZ.muted}" text-anchor="end">${CH.esc(opts.xhi || '')}</text>`
    + `<text x="${padL - 8}" y="${h - 12}" font-size="13" fill="${VIZ.muted}" text-anchor="end">${CH.esc(opts.ylabel || 'pooled HR')}</text></svg>`;
}

/** Funnel plot: one trial per point, effect against precision, on a log-HR axis.
 *  f: the backend `funnel` block. Two series only (published, registry-only);
 *  the pair #4a7fb5 / #d9722c passes every validator check under --pairs all. */
function funnelplot(f, opts = {}) {
  const pts = (f && f.points) || [];
  if (!pts.length) return '<p class="empty">No poolable hazard ratios to plot.</p>';
  const W = 100, H = 64, padL = 3, padR = 3, padT = 4, padB = 9;
  const logs = pts.map(p => p.log_hr);
  const bounds = f.bounds || [];
  const lo = Math.min(...logs, ...bounds.map(b => Math.log(b.lower)), Math.log(0.5)) - 0.08;
  const hi = Math.max(...logs, ...bounds.map(b => Math.log(b.upper)), Math.log(1.5)) + 0.08;
  const maxSe = Math.max(...pts.map(p => p.standard_error)) * 1.06;
  const X = v => padL + (v - lo) / (hi - lo) * (W - padL - padR);
  const Y = se => padT + se / maxSe * (H - padT - padB);
  const centre = f.pooled_log_hr;
  const colorFor = p => p.category === 'registry_only_with_result' ? VIZ.accent : VIZ.published;
  // The CSS pins this box to the same 100:64 ratio as the viewBox, so the
  // default preserveAspectRatio is exact and the tick labels are not stretched.
  let out = `<svg class="chart funnel" viewBox="0 0 ${W} ${H}" role="img" aria-label="${CH.esc(opts.title || 'funnel plot')}">`;
  // Pseudo 95% region around the pooled estimate: a wedge from the apex down.
  if (centre != null && bounds.length) {
    const left = bounds.map(b => `${X(Math.log(b.lower)).toFixed(2)},${Y(b.se).toFixed(2)}`);
    const right = bounds.map(b => `${X(Math.log(b.upper)).toFixed(2)},${Y(b.se).toFixed(2)}`).reverse();
    out += `<polygon points="${X(centre).toFixed(2)},${Y(0).toFixed(2)} ${left.join(' ')} ${right.join(' ')}" fill="${VIZ.grid}" opacity=".45"/>`
      + `<line x1="${X(centre)}" y1="${Y(0)}" x2="${X(centre)}" y2="${H - padB}" stroke="${VIZ.muted}" stroke-width="0.5" stroke-dasharray="1.5 1.5"/>`;
  }
  // The null: no difference between arms.
  if (lo < 0 && hi > 0) out += `<line x1="${X(0)}" y1="${padT}" x2="${X(0)}" y2="${H - padB}" stroke="${VIZ.ink}" stroke-width="0.5" opacity=".5"/>`;
  out += `<line x1="${padL}" y1="${H - padB}" x2="${W - padR}" y2="${H - padB}" stroke="${VIZ.grid}" stroke-width="0.5"/>`;
  // Registry-only points are drawn last so they sit on top: they are the ones the reader is looking for.
  const ordered = pts.slice().sort((a, b) => (a.category === 'registry_only_with_result') - (b.category === 'registry_only_with_result'));
  ordered.forEach(p => {
    out += `<g><title>${CH.esc(p.nct_id)} · ${CH.esc(p.category === 'registry_only_with_result' ? 'registry result, no publication identified' : 'published, with a result')}\nHR ${CH.num(p.hazard_ratio)} (95% CI ${CH.num(p.ci_lower)}–${CH.num(p.ci_upper)}) · SE ${CH.num(p.standard_error, 3)}${p.enrollment ? ` · ${CH.int(p.enrollment)} enrolled` : ''}\n${CH.esc(p.title || '')}</title>`
      + `<circle cx="${X(p.log_hr).toFixed(2)}" cy="${Y(p.standard_error).toFixed(2)}" r="1.7" fill="${colorFor(p)}" stroke="${VIZ.surface}" stroke-width="0.6"/></g>`;
  });
  [0.25, 0.5, 1, 2].forEach(t => {
    const v = Math.log(t);
    if (v >= lo && v <= hi) out += `<text x="${X(v)}" y="${H - 2}" font-size="4.5" fill="${VIZ.muted}" text-anchor="middle">${t === 1 ? 'HR 1' : t}</text>`;
  });
  out += `<text x="${padL}" y="${padT + 3}" font-size="4" fill="${VIZ.muted}">precise ↑</text>`
    + `<text x="${padL}" y="${H - padB - 1.5}" font-size="4" fill="${VIZ.muted}">imprecise ↓</text></svg>`;
  const nA = pts.filter(p => p.category !== 'registry_only_with_result').length, nB = pts.length - nA;
  out += '<div class="chartlabels">'
    + `<div class="chartrow"><span class="chip" style="background:${VIZ.published}"></span><span class="rowlabel">Published, with a result</span><b>${CH.int(nA)}</b></div>`
    + `<div class="chartrow"><span class="chip" style="background:${VIZ.accent}"></span><span class="rowlabel">Registry result, no publication identified</span><b>${CH.int(nB)}</b></div>`
    + `<div class="chartrow"><span class="chip" style="background:${VIZ.grid}"></span><span class="rowlabel">Pseudo 95% region around the registry-aware pooled estimate${centre != null ? ` (HR ${CH.num(Math.exp(centre))})` : ''}</span></div>`
    + '</div>';
  return out;
}
