// The three views that are not about citations: bias-aware trial design,
// reviewer conflicts, and the registered-versus-published comparison.

async function callJSON(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) throw Error(payload.error || 'That request could not be completed.');
  return payload;
}

function guard(button, text) {
  if (busy) return false;
  busy = true; $('#' + button).disabled = true; message(text); return true;
}
function release(button) { busy = false; $('#' + button).disabled = false; }

// --- Bias-aware trial design ---------------------------------------------

// Saved cohorts analyse instantly; anything else needs a multi-minute rebuild,
// so the interface says up front which ones are ready.
async function listCohorts() {
  try {
    const payload = await callJSON('/api/cohorts');
    if (!payload.cohorts.length) return;
    $('#searchsources').textContent = 'Any disease area works; a new cohort takes about ten seconds. '
      + 'Instant from cache: ' + payload.cohorts
        .map(c => `${c.condition} (${c.endpoint_class.toUpperCase()})`).join(' · ');
  } catch (e) { /* the hint is a convenience; its absence is not an error */ }
}

async function runDesign() {
  if (!guard('rundesign', 'Building the registry cohort and matching it to the published record. A new disease area takes about ten seconds…')) return;
  try {
    design = await callJSON('/api/design?' + new URLSearchParams({
      condition: $('#condition').value, endpoint: $('#endpoint').value,
      hr: $('#hr').value, power: $('#power').value, alpha: $('#alpha').value,
    }));
    renderDesign(); message(''); listCohorts();
  } catch (e) { message(e.message, true); }
  finally { release('rundesign'); }
}

function renderDesign() {
  const d = design, c = d.cohort, cat = c.categories, p = d.priors, lit = p.literature_only, reg = p.registry_aware;
  const rows = d.design.rows, con = d.design.consequence, back = d.backtest, sens = d.sensitivity;
  const sig = d.linkage.by_significance, dir = d.linkage.by_direction;

  const linkRows = sig && sig.significant ? [
    {label: 'Statistically significant', value: sig.significant.linkage_rate, display: CH.pct(sig.significant.linkage_rate), note: `${sig.significant.n} trials`, color: VIZ.accent},
    {label: 'Not significant', value: sig.not_significant.linkage_rate, display: CH.pct(sig.not_significant.linkage_rate), note: `${sig.not_significant.n} trials`, color: VIZ.context},
    {label: 'Favours treatment', value: dir.favors_treatment.linkage_rate, display: CH.pct(dir.favors_treatment.linkage_rate), note: `${dir.favors_treatment.n} trials`, color: VIZ.accent},
    {label: 'Favours control', value: dir.favors_control.linkage_rate, display: CH.pct(dir.favors_control.linkage_rate), note: `${dir.favors_control.n} trials`, color: VIZ.context},
  ] : [];

  $('#designpanel').innerHTML = `
<div class="sectionhead"><div><span class="eyebrow">BIAS-AWARE TRIAL DESIGN</span><h2>${CH.esc(c.condition)} · ${CH.esc(c.endpoint_class.toUpperCase())} · phase ${CH.esc(c.phases.join('/'))}</h2></div><div class="sourcepill">● ${CH.int(c.trials)} completed registered trials with posted results</div></div>

<div class="vizgrid">
  <section class="vizcard"><h3>1 · What the literature is missing</h3>
    <p class="vizsub">Completed trials, grouped by whether their results are findable in the published record.</p>
    ${stackbar([
      {label: 'Published, with a result', value: cat.A_published_with_result, color: VIZ.good},
      {label: 'Registry result, no publication found', value: cat.B_registry_only_with_result, color: VIZ.accent, note: 'the observable gap'},
      {label: 'No publication, no usable result', value: cat.C_no_publication_no_result, color: VIZ.context, note: 'sensitivity analysis only'},
    ], {title: 'trial categories'})}
  </section>

  <section class="vizcard"><h3>2 · Publication tracks the result</h3>
    <p class="vizsub">Share of trials with an identified publication, among those that posted a usable result.</p>
    ${linkRows.length ? hbar(linkRows, {max: 1, title: 'linkage rate'}) : '<p class="empty">Too few trials with usable results to break down.</p>'}
    <p class="rownote">${CH.esc(d.linkage.caveat || '')}</p>
  </section>
</div>

<section class="vizcard"><h3>3 · Two priors from the same cohort</h3>
  <p class="vizsub">Pooled hazard ratio, random effects. Adding registry-only results is the correction.</p>
  ${forest([
    {label: 'Literature-only', value: lit.hazard_ratio, lo: lit.ci_lower, hi: lit.ci_upper, k: lit.k, color: VIZ.context, sub: `${lit.k} trials`},
    {label: 'Registry-aware', value: reg.hazard_ratio, lo: reg.ci_lower, hi: reg.ci_upper, k: reg.k, color: VIZ.accent, sub: `${reg.k} trials`},
  ], {title: 'pooled hazard ratio'})}
  <p class="viznote">${CH.esc(p.interpretation)}</p>
  <p class="rownote">${CH.esc(p.caveat)}</p>
</section>

<section class="vizcard"><h3>4 · What that does to your design</h3>
  <p class="vizsub">alpha ${CH.esc(d.design.alpha)} · target power ${CH.pct(d.design.target_power)} · Schoenfeld, 1:1 allocation.</p>
  <table class="datatable"><thead><tr><th>Basis</th><th>HR</th><th>Events needed</th><th>Power delivered</th></tr></thead><tbody>
  ${rows.map(r => `<tr${r.label === 'Registry-aware estimate' ? ' class="highlight"' : ''}><td>${CH.esc(r.label)}</td>
    <td>${r.hazard_ratio === r.hazard_ratio ? CH.num(r.hazard_ratio) : '--'}</td>
    <td>${r.required_events ? CH.int(r.required_events) : '<span class="rownote">not feasible</span>'}</td>
    <td>${r.power_at_planned_events != null ? CH.pct(r.power_at_planned_events) : '--'}</td></tr>`).join('')}
  </tbody></table>
  ${con ? `<div class="meterrow">
     ${meter(d.design.target_power, null, 'Power you designed for')}
     ${meter(con.delivered_power_if_registry_aware_is_true, d.design.target_power, 'Power actually delivered', `if the registry-aware estimate is closer to the truth`)}
   </div><p class="viznote">${CH.esc(con.summary)}</p>` : ''}
</section>

<div class="vizgrid">
  <section class="vizcard"><h3>5 · If the unknown trials were known</h3>
    <p class="vizsub">${CH.int(sens.unknown_trials)} trials have neither a publication nor a posted result. Their effect is assumed, not imputed.</p>
    ${sens.points && sens.points.length ? linechart(
      sens.points.map(pt => ({y: pt.pooled_hazard_ratio,
        label: `assume HR ${CH.num(pt.assumed_hazard_ratio_for_unknowns)} → pooled HR ${CH.num(pt.pooled_hazard_ratio, 3)}${pt.required_events ? `, ${CH.int(pt.required_events)} events` : ', not feasible'}`})),
      {title: 'sensitivity sweep', xlo: `assume HR ${CH.num(sens.points[0].assumed_hazard_ratio_for_unknowns)}`, xhi: `HR ${CH.num(sens.points[sens.points.length - 1].assumed_hazard_ratio_for_unknowns)}`}) : ''}
    <p class="rownote">${CH.esc(sens.note || '')}</p>
  </section>

  <section class="vizcard"><h3>6 · Does the correction actually help?</h3>
    ${back.ran ? `<p class="vizsub">Leave-one-out over ${back.n} trials, ${CH.pct(back.level)} prediction interval.</p>
    <table class="datatable"><thead><tr><th>Model</th><th>Coverage</th><th>MAE log(HR)</th><th>Bias</th></tr></thead><tbody>
    ${[['literature_only', 'Literature-only'], ['registry_aware', 'Registry-aware']].map(([k, label]) => {
      const b = back.summary[k] || {};
      return `<tr><td>${label}</td><td>${b.n ? CH.pct(b.coverage) : '--'}</td><td>${b.n ? CH.num(b.mean_absolute_error_log_hr, 3) : '--'}</td><td>${b.n ? (b.bias_log_hr > 0 ? '+' : '') + CH.num(b.bias_log_hr, 3) : '--'}</td></tr>`;
    }).join('')}</tbody></table>
    <p class="viznote">${CH.esc(back.verdict)}</p>` : `<p class="empty">${CH.esc(back.note || 'Back-test did not run.')}</p>`}
  </section>
</div>

<details class="methods"><summary>How these numbers were produced</summary>
  ${d.guardrails.map(g => `<p>· ${CH.esc(g)}</p>`).join('')}
  <p>${CH.esc(d.design.method)}</p><p>${CH.esc(back.method || '')}</p>
</details>`;
}

// --- Reviewer conflicts ---------------------------------------------------

async function runReviewer() {
  if (!guard('runreviewer', 'Resolving authors and expanding their coauthorship neighbourhoods…')) return;
  try {
    const since = parseInt($('#sinceyear').value, 10);
    reviewer = await callJSON('/api/reviewer-conflict', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        candidate_reviewer: $('#reviewer').value,
        manuscript_authors: $('#authors').value.split(',').map(a => a.trim()).filter(Boolean),
        max_hops: parseInt($('#hops').value, 10),
        since_year: Number.isFinite(since) ? since : null,
      }),
    });
    renderReviewer(); message('');
  } catch (e) { message(e.message, true); }
  finally { release('runreviewer'); }
}

function renderReviewer() {
  const r = reviewer, min = r.minimum_distance;
  const tone = min === null ? 'ok' : min <= 1 ? 'bad' : min <= 2 ? 'warn' : 'ok';
  const verdict = min === null ? 'No coauthorship path found within the searched range'
    : min === 0 ? 'The candidate reviewer is also a manuscript author'
    : min === 1 ? 'The candidate reviewer has coauthored directly with a manuscript author'
    : `Closest connection is ${min} hops away`;

  $('#reviewerpanel').innerHTML = `
<div class="sectionhead"><div><span class="eyebrow">REVIEWER CONFLICT CHECK</span><h2>${CH.esc(r.reviewer_name || r.reviewer)}</h2></div><div class="sourcepill">● ${CH.int(r.graph_size ? r.graph_size.authors : 0)} authors · ${CH.int(r.graph_size ? r.graph_size.edges : 0)} coauthorship links searched</div></div>
<div class="verdict ${tone}"><b>${CH.esc(verdict)}</b><span>Searched up to ${r.searched_max_hops} hop(s)${r.since_year ? ` since ${r.since_year}` : ''}. This is a description of a relationship, not a policy judgement.</span></div>
${(r.unresolved_authors || []).length ? `<p class="rownote">Could not resolve in OpenAlex: ${CH.esc(r.unresolved_authors.join(', '))}</p>` : ''}
<div class="flaglist">
${r.results.map(entry => `<article class="flagcard ${entry.distance === null ? '' : entry.distance <= 1 ? 'bad' : 'warn'}">
  <div class="flaghead"><span class="badge ${entry.distance !== null && entry.distance <= 1 ? '' : 'neutral'}">${entry.distance === null ? 'No path found' : `Distance ${entry.distance}`}</span><span class="small">${entry.path_count ? CH.int(entry.path_count) + ' path(s)' : ''}</span></div>
  <h4>${CH.esc(entry.manuscript_author_name || entry.manuscript_author)}</h4>
  ${entry.note ? `<p class="rownote">${CH.esc(entry.note)}</p>` : ''}
  ${entry.summary ? `<p class="viznote">${CH.esc(entry.summary)}</p>` : ''}
  ${(entry.paths || []).slice(0, 3).map(path => `<div class="pathchain">
    ${path.author_names.map((name, i) => `${i ? '<span class="pathlink">coauthored with</span>' : ''}<span class="pathnode">${CH.esc(name)}</span>`).join('')}
  </div>
  ${path.steps.map(step => `<div class="evidencebox"><p><b>${CH.esc(step.from_name)} → ${CH.esc(step.to_name)}</b> · ${CH.int(step.shared_work_count)} shared work(s)${step.first_collaboration_year ? ` · ${step.first_collaboration_year}–${step.most_recent_collaboration_year}` : ''}</p>
    ${step.works.slice(0, 2).map(w => `<a href="${w.doi ? 'https://doi.org/' + CH.esc(w.doi) : CH.esc(w.openalex_work)}" target="_blank" rel="noreferrer">${w.year || '----'} · ${CH.esc(w.title || 'Untitled work')} ↗</a>`).join('')}
  </div>`).join('')}`).join('')}
</article>`).join('')}
</div>
<details class="methods" open><summary>How to read this</summary><p>${CH.esc(r.interpretation)}</p>
<p>Paths come from the OpenAlex coauthorship graph, expanded outward from the named people rather than from a global graph. Papers with very large author lists are skipped, because they connect hundreds of people who never worked together directly. A path not found is not proof that no relationship exists.</p></details>`;
}

// --- Registered versus published -----------------------------------------

async function runTrial() {
  if (!guard('runtrial', 'Fetching the registration and matching it to the published record…')) return;
  try {
    trial = await callJSON('/api/trial?' + new URLSearchParams({nct: $('#nct').value, limit: 6}));
    renderTrial(); message('');
  } catch (e) { message(e.message, true); }
  finally { release('runtrial'); }
}

const FIELD_TONE = {match: 'ok', difference: 'warn', not_found: 'bad', not_registered: 'bad', not_comparable: 'muted'};
const FIELD_WORD = {match: 'match', difference: 'DIFFERENCE', not_found: 'not identified', not_registered: 'not registered', not_comparable: 'not comparable'};

function renderTrial() {
  const t = trial.trial, pubs = trial.publications;
  const top = pubs[0];
  $('#trialpanel').innerHTML = `
<div class="sectionhead"><div><span class="eyebrow">REGISTERED VS PUBLISHED</span><h2>${CH.esc(t.title)}</h2></div><div class="sourcepill">● ${CH.esc(t.nct_id)} · ${CH.esc(t.status || '')}</div></div>
<div class="verdict ok"><b>${CH.int(trial.publication_count)} linked publication(s)</b><span>${CH.esc(t.lead_sponsor || 'sponsor unavailable')} · phase ${CH.esc((t.phases || []).join('/'))} · enrollment ${CH.int(t.enrollment)} (${CH.esc((t.enrollment_type || '').toLowerCase())}) · registered primary outcome: ${CH.esc((t.primary_outcomes || []).join('; ') || 'none listed')}</span></div>
${pubs.length ? `<section class="vizcard"><h3>Which publication actually reports this trial?</h3>
<p class="vizsub">Ranked by how much of the registered trial each one reports — a declared registry identifier proves a paper concerns the trial, not that it reports it.</p>
<div class="publist">${pubs.map((p, i) => `<button class="paperrow${i === 0 ? ' active' : ''}" data-pub="${i}">
  <i style="background:${p.role === 'primary_results' ? VIZ.good : p.role === 'mentions_trial' ? VIZ.context : VIZ.accent};flex-shrink:0"></i>
  <div>${CH.esc(p.title)}<span>${CH.esc(p.publication_date || '')} · ${CH.esc(p.role_label)} · ${Object.entries(p.comparison.counts).map(([k, v]) => `${FIELD_WORD[k] || k} ${v}`).join(' · ')}</span></div></button>`).join('')}</div>
</section>
<section class="vizcard" id="comparecard">${comparisonTable(top)}</section>`
  : '<p class="empty">The registry record links no publications.</p>'}
<details class="methods"><summary>Sources</summary><p><a href="${CH.esc(t.url)}" target="_blank" rel="noreferrer">${CH.esc(t.nct_id)} on ClinicalTrials.gov ↗</a></p><p>${CH.esc(trial.sampling)}</p></details>`;

  document.querySelectorAll('[data-pub]').forEach(el => el.onclick = () => {
    document.querySelectorAll('[data-pub]').forEach(o => o.classList.remove('active'));
    el.classList.add('active');
    $('#comparecard').innerHTML = comparisonTable(pubs[parseInt(el.dataset.pub, 10)]);
  });
}

function comparisonTable(pub) {
  const c = pub.comparison;
  return `<h3>${CH.esc(pub.title)}</h3>
<p class="vizsub">${CH.esc(pub.journal || '')} · ${CH.esc(pub.publication_date || '')} · linked by ${c.match_basis === 'identifier' ? 'a declared registry identifier' : 'inferred metadata'} (confidence ${CH.esc(c.match_confidence)}) · ${CH.esc(pub.role_label)}</p>
<table class="datatable"><thead><tr><th>Field</th><th>Registered</th><th>Published</th><th>Status</th></tr></thead><tbody>
${c.fields.map(f => `<tr><td>${CH.esc(f.field_name)}</td><td>${CH.esc(f.registered || '--')}</td><td>${CH.esc(f.published || '--')}</td>
  <td><span class="tag ${FIELD_TONE[f.status] || 'muted'}">${CH.esc(FIELD_WORD[f.status] || f.status)}</span></td></tr>
  ${f.note && (f.status === 'difference' || f.status === 'not_found') ? `<tr class="noterow"><td colspan="4"><span class="rownote">${CH.esc(f.note)}</span></td></tr>` : ''}`).join('')}
</tbody></table>
<p class="rownote">${CH.esc(c.evidence_scope)}</p>
<p class="rownote">Differences are reported as differences. They are not, on their own, evidence of error or misconduct.</p>
<p><a class="external" href="${CH.esc(pub.url)}" target="_blank" rel="noreferrer">Open on PubMed ↗</a></p>`;
}
