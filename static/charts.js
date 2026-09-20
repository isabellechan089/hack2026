// Small inline-SVG chart primitives.
//
// Shared rules, applied by every primitive here:
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

/** Horizontal bars. rows: [{label, value, display, color?, note?}] */
function hbar(rows, opts = {}) {
  const max = opts.max ?? Math.max(...rows.map(r => r.value || 0), 0.0001);
  const w = 100, labelW = opts.labelWidth ?? 40, barW = w - labelW - 14;
  const rowH = 30, h = rows.length * rowH + 6;
  let out = `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="${CH.esc(opts.title || 'bar chart')}" preserveAspectRatio="none">`;
  rows.forEach((r, i) => {
    const y = i * rowH + 6, len = Math.max(0.6, (r.value || 0) / max * barW);
    const color = r.color || VIZ.accent;
    out += `<g><title>${CH.esc(r.label)}: ${CH.esc(r.display ?? r.value)}${r.note ? ' — ' + CH.esc(r.note) : ''}</title>`
      + `<rect x="0" y="${y}" width="${w}" height="${rowH - 6}" fill="transparent"/>`
      + `<rect x="${labelW}" y="${y + 3}" width="${len}" height="12" rx="4" fill="${color}"/></g>`;
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

/** Forest plot on a log scale. rows: [{label, value, lo, hi, color, k, sub}] */
function forest(rows, opts = {}) {
  const usable = rows.filter(r => r.value);
  if (!usable.length) return '<p class="empty">No poolable estimate for this cohort.</p>';
  const lo = Math.min(...usable.map(r => r.lo ?? r.value), 1) * 0.92;
  const hi = Math.max(...usable.map(r => r.hi ?? r.value), 1) * 1.08;
  const L = Math.log(lo), H = Math.log(hi);
  const X = v => (Math.log(v) - L) / (H - L) * 100;
  const rowH = 34, h = rows.length * rowH + 22;
  let out = `<svg class="chart forest" viewBox="0 0 100 ${h}" role="img" aria-label="${CH.esc(opts.title || 'pooled effect estimates')}" preserveAspectRatio="none">`;
  // Reference line at a hazard ratio of 1: no difference between arms.
  if (lo < 1 && hi > 1) out += `<line x1="${X(1)}" y1="0" x2="${X(1)}" y2="${h - 20}" stroke="${VIZ.grid}" stroke-width="0.5" stroke-dasharray="2 2"/>`;
  rows.forEach((r, i) => {
    if (!r.value) return;
    const y = i * rowH + 18, c = r.color || VIZ.accent;
    if (r.lo && r.hi) out += `<line x1="${X(r.lo)}" y1="${y}" x2="${X(r.hi)}" y2="${y}" stroke="${c}" stroke-width="2" stroke-linecap="round"/>`;
    out += `<g><title>${CH.esc(r.label)}: HR ${CH.num(r.value, 3)}${r.lo ? ` (95% CI ${CH.num(r.lo, 3)}–${CH.num(r.hi, 3)})` : ''}${r.k ? `, ${r.k} trials` : ''}</title>`
      + `<circle cx="${X(r.value)}" cy="${y}" r="3.2" fill="${c}" stroke="${VIZ.surface}" stroke-width="1.2"/></g>`;
  });
  out += `<text x="0" y="${h - 4}" font-size="5" fill="${VIZ.muted}">HR ${CH.num(lo, 2)}</text>`
    + (lo < 1 && hi > 1 ? `<text x="${X(1)}" y="${h - 4}" font-size="5" fill="${VIZ.muted}" text-anchor="middle">1.0</text>` : '')
    + `<text x="100" y="${h - 4}" font-size="5" fill="${VIZ.muted}" text-anchor="end">HR ${CH.num(hi, 2)}</text></svg>`;
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

/** A single line over an ordered x. points: [{x, y, label}] */
function linechart(points, opts = {}) {
  const ys = points.map(p => p.y).filter(v => v != null);
  if (ys.length < 2) return '';
  const ymin = Math.min(...ys), ymax = Math.max(...ys), span = (ymax - ymin) || 1;
  const h = 70, pad = 8;
  const X = i => i / (points.length - 1) * 100;
  const Y = v => h - pad - (v - ymin) / span * (h - pad * 2);
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${X(i).toFixed(2)},${Y(p.y).toFixed(2)}`).join(' ');
  let out = `<svg class="chart" viewBox="0 0 100 ${h}" role="img" aria-label="${CH.esc(opts.title || 'sensitivity')}" preserveAspectRatio="none">`
    + `<line x1="0" y1="${Y(ymin)}" x2="100" y2="${Y(ymin)}" stroke="${VIZ.grid}" stroke-width="0.5"/>`
    + `<path d="${path}" fill="none" stroke="${VIZ.accent}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>`;
  points.forEach((p, i) => {
    out += `<g><title>${CH.esc(p.label)}</title><circle cx="${X(i)}" cy="${Y(p.y)}" r="2.6" fill="${VIZ.accent}" stroke="${VIZ.surface}" stroke-width="1.2"/></g>`;
  });
  return out + `<text x="0" y="${h - 1}" font-size="5" fill="${VIZ.muted}">${CH.esc(opts.xlo || '')}</text>`
    + `<text x="100" y="${h - 1}" font-size="5" fill="${VIZ.muted}" text-anchor="end">${CH.esc(opts.xhi || '')}</text></svg>`;
}
