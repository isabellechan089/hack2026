// The views that are not about citations: bias-aware trial design (with its
// funnel plot, cross-cohort overview and cost ledger), reviewer conflicts, the
// registered-versus-published comparison, the fuzzy cascade and index search.

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
    const byCondition = {};
    payload.cohorts.forEach(c => { (byCondition[c.condition] = byCondition[c.condition] || []).push(c.endpoint_class.toUpperCase()); });
    $('#searchsources').textContent = 'Any disease area works; a new cohort builds in about ten seconds and is kept. '
      + 'Instant now: ' + Object.entries(byCondition).map(([k, v]) => `${k} (${v.join(', ')})`).join(' · ');
  } catch (e) { /* the hint is a convenience; its absence is not an error */ }
}

async function runDesign() {
  if (!guard('rundesign', 'Building the registry cohort and matching it to the published record. A new disease area takes about ten seconds…')) return;
  try {
    const recover = $('#recover').checked;
    if (recover) message('Building the cohort, then reading open full text for trials with no posted estimate. This can take a minute…');
    const params = {
      condition: $('#condition').value, endpoint: $('#endpoint').value,
      hr: $('#hr').value, power: $('#power').value, alpha: $('#alpha').value,
      recover: recover ? '1' : '0',
    };
    const eventProbability = parseFloat($('#eventprob').value);
    if (Number.isFinite(eventProbability) && eventProbability > 0 && eventProbability <= 1) params.event_probability = eventProbability;
    design = await callJSON('/api/design?' + new URLSearchParams(params));
    renderDesign(); message(''); listCohorts();
    // Two cards that depend on other endpoints fill in after the analysis, so
    // the analysis never waits on the ledger or on the other saved cohorts.
    loadOverview(); loadLedger();
  } catch (e) { message(e.message, true); }
  finally { release('rundesign'); }
}

// A plain-language reading of THIS cohort's actual numbers. The charts show
// what happened; this says what it means, and says it differently when the
// cohort does not behave the way the hypothesis predicts.
function readingGuide(d) {
  const c = d.cohort, cat = c.categories, pr = d.priors;
  const lit = pr.literature_only, reg = pr.registry_aware;
  const sig = (d.linkage || {}).by_significance || {};
  const yes = sig.significant || {}, no = sig.not_significant || {};
  const con = (d.design || {}).consequence;
  const assumed = d.design ? d.design.assumed_hazard_ratio : null;
  const target = d.design ? d.design.target_power : null;
  const steps = [];

  steps.push(`<b>What is in the cohort.</b> Every completed phase ${CH.esc(c.phases.join('/'))}
    ${CH.esc(c.condition)} trial that posted results to ClinicalTrials.gov: ${CH.int(c.trials)} of them.
    Only ${CH.int(c.with_usable_effect)} posted a hazard ratio with a confidence interval, which is the
    only form of result that can be pooled with the others. The remaining ${CH.int(cat.C_no_usable_result)}
    are counted and described in section 1, never filled in with a guessed value.`);

  if (yes.n && no.n) {
    const gap = (yes.linkage_rate || 0) - (no.linkage_rate || 0);
    steps.push(gap > 0.05
      ? `<b>The test, in section 2.</b> Among the trials that did post a usable number,
         ${CH.pct(yes.linkage_rate)} of the statistically significant ones have a publication we could
         find, against ${CH.pct(no.linkage_rate)} of the ones that were not significant. Trials that
         worked are easier to find in the literature than trials that did not. That gap is the whole
         premise, and it is counted rather than assumed.`
      : gap < -0.05
      ? `<b>The test, in section 2.</b> Here the expected pattern does not appear: the significant
         trials were linked to a publication ${CH.pct(yes.linkage_rate)} of the time, and the ones that
         were not significant ${CH.pct(no.linkage_rate)} of the time. Read this cohort as evidence
         against strong selection, not as a broken result. The tool reports the direction it finds.`
      : `<b>The test, in section 2.</b> Significant and non-significant trials were linked at almost the
         same rate, ${CH.pct(yes.linkage_rate)} against ${CH.pct(no.linkage_rate)}. No meaningful
         selection is observable in this cohort.`);
  }

  if (lit.hazard_ratio && reg.hazard_ratio) {
    const moved = reg.hazard_ratio - lit.hazard_ratio;
    const direction = Math.abs(moved) < 0.005 ? 'barely moved'
      : moved > 0 ? 'moved toward 1.0, meaning a weaker average effect'
      : 'moved away from 1.0, meaning a stronger average effect';
    steps.push(`<b>The correction, in section 3.</b> The same cohort is pooled twice. Literature-only
      uses the ${CH.int(lit.k)} trials a reader could have found: HR ${CH.num(lit.hazard_ratio, 3)}.
      Registry-aware adds the ${CH.int(pr.trials_added)} whose results exist only in the registry:
      HR ${CH.num(reg.hazard_ratio, 3)}. Adding them ${direction}. A hazard ratio below 1 favours the
      treatment, so the lower the number, the larger the benefit it claims.`);
  }

  if (con && assumed) {
    steps.push(`<b>What it costs you, in section 5.</b> You assumed HR ${CH.num(assumed)}, which needs
      ${CH.int(con.planned_events)} events to reach ${CH.pct(target)} power. If the registry-aware
      estimate of HR ${CH.num(reg.hazard_ratio)} is closer to the truth, those same
      ${CH.int(con.planned_events)} events deliver ${CH.pct(con.delivered_power_if_registry_aware_is_true)}
      instead. That is the headline: a trial that looks adequately powered on paper, and is not.`);
  }

  if (reg.hazard_ratio && reg.hazard_ratio > 0.9) {
    steps.push(`<b>Read this cohort with care.</b> Its pooled estimate sits close to HR 1.0, so the
      average trial in it showed little benefit. An assumed HR of ${CH.num(assumed)} is then a strong
      claim, and the very large event counts in section 5 are the arithmetic of chasing an effect this
      evidence base does not support. That is a real finding about the disease area, not a failure of
      the calculation.`);
  }

  return `<section class="vizcard guide"><h3>How to read this page</h3>
    <p class="vizsub">Written from this cohort's own numbers, so it changes when the cohort does.</p>
    ${steps.map(t => `<p class="guidestep">${t}</p>`).join('')}
    <p class="rownote">Sections 4, 6 and 7 are the checks: does the missing evidence sit where selection
    would put it, how much could the genuinely unknown trials move the answer, and does the correction
    predict held-out trials better than the literature does.</p>
  </section>`;
}

function renderDesign() {
  const d = design, c = d.cohort, cat = c.categories, p = d.priors, lit = p.literature_only, reg = p.registry_aware;
  const rows = d.design.rows, con = d.design.consequence, back = d.backtest, sens = d.sensitivity;
  const sig = d.linkage.by_significance, dir = d.linkage.by_direction;
  const src = c.sources || {}, fun = d.funnel || {}, egger = fun.egger || {};
  const withParticipants = rows.some(r => r.required_participants);

  const linkRows = sig && sig.significant ? [
    {label: 'Statistically significant', value: sig.significant.linkage_rate, display: CH.pct(sig.significant.linkage_rate), note: `${sig.significant.n} trials`, color: VIZ.accent},
    {label: 'Not significant', value: sig.not_significant.linkage_rate, display: CH.pct(sig.not_significant.linkage_rate), note: `${sig.not_significant.n} trials`, color: VIZ.context},
    {label: 'Favours treatment', value: dir.favors_treatment.linkage_rate, display: CH.pct(dir.favors_treatment.linkage_rate), note: `${dir.favors_treatment.n} trials`, color: VIZ.accent},
    {label: 'Favours control', value: dir.favors_control.linkage_rate, display: CH.pct(dir.favors_control.linkage_rate), note: `${dir.favors_control.n} trials`, color: VIZ.context},
  ] : [];

  $('#designpanel').innerHTML = `
<div class="sectionhead"><div><span class="eyebrow">BIAS-AWARE TRIAL DESIGN</span><h2>${CH.esc(c.condition)} · ${CH.esc(c.endpoint_class.toUpperCase())} · phase ${CH.esc(c.phases.join('/'))}</h2></div><div class="sourcepill">● ${CH.int(c.trials)} completed registered trials with posted results</div></div>
${readingGuide(d)}
${src.registry_trials ? `<p class="rownote provenance">Sources · ${CH.int(src.registry_trials)} registrations from ClinicalTrials.gov · ${CH.int(src.publications_linked)} publications via PubMed · ${CH.int(src.openalex_resolved)} resolved in the OpenAlex graph${src.retracted_publications ? ` · ${CH.int(src.retracted_publications)} carry a retraction flag` : ' · none flagged as retracted'}</p>` : ''}

<div class="vizgrid">
  <section class="vizcard"><h3>1 · What the literature is missing</h3>
    <p class="vizsub">Completed trials, grouped by whether their results are findable in the published record.</p>
    ${stackbar([
      {label: 'Published, with a result', value: cat.A_published_with_result, color: VIZ.published},
      {label: 'Registry result, no publication found', value: cat.B_registry_only_with_result, color: VIZ.accent, note: 'the observable gap'},
      {label: 'No usable effect estimate', value: cat.C_no_usable_result, color: VIZ.context, note: 'sensitivity analysis only'},
    ], {title: 'trial categories'})}
    ${c.no_result_breakdown ? `<p class="rownote" style="margin-top:12px">Of the ${CH.int(cat.C_no_usable_result)} without a usable estimate, ${CH.int(c.no_result_breakdown.with_publication_identified)} do have a publication. ${Object.entries(c.no_result_breakdown.reasons).map(([k, v]) => `${CH.esc(k)}: ${CH.int(v)}`).join(' · ')}.</p>` : ''}
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
    {label: 'Literature-only', value: lit.hazard_ratio, lo: lit.ci_lower, hi: lit.ci_upper, k: lit.k, color: VIZ.published, sub: `${lit.k} trials`},
    {label: 'Registry-aware', value: reg.hazard_ratio, lo: reg.ci_lower, hi: reg.ci_upper, k: reg.k, color: VIZ.accent, sub: `${reg.k} trials`},
  ], {title: 'pooled hazard ratio'})}
  <p class="viznote">${CH.esc(p.interpretation)}</p>
  <p class="rownote">${CH.esc(p.caveat)}</p>
</section>

<section class="vizcard"><h3>4 · Where the missing trials sit</h3>
  <p class="vizsub">Each trial by its effect and its precision. Publication selection hollows out one corner: small trials with unimpressive results. The registry-only trials should land there.</p>
  <div class="funnelgrid">
    <div>${funnelplot(fun, {title: 'funnel plot'})}</div>
    <div>
      <table class="datatable"><thead><tr><th>Egger's test</th><th>Trials</th><th>Intercept</th><th>p</th></tr></thead><tbody>
      ${[['literature_only', 'Literature-only', VIZ.published], ['registry_aware', 'Registry-aware', VIZ.accent]].map(([k, label, color]) => {
        const e = egger[k] || {};
        return `<tr><td><span class="chip" style="background:${color};display:inline-block;margin-right:7px"></span>${label}</td><td>${CH.int(e.k)}</td><td>${e.ran ? (e.intercept > 0 ? '+' : '') + CH.num(e.intercept) + ' ± ' + CH.num(e.intercept_se) : '--'}</td><td>${e.ran ? (e.p_value < 0.001 ? '<0.001' : CH.num(e.p_value, 3)) : '--'}</td></tr>`;
      }).join('')}</tbody></table>
      ${egger.literature_only && egger.literature_only.note ? `<p class="viznote">${CH.esc(egger.literature_only.note)}${egger.registry_aware && egger.registry_aware.ran ? ` Adding the registry-only trials moves the intercept from ${CH.num(egger.literature_only.intercept)} to ${CH.num(egger.registry_aware.intercept)}.` : ''}</p>` : ''}
      ${fun.placement ? `<p class="rownote">${CH.esc(fun.placement.note)}</p>` : ''}
    </div>
  </div>
  <p class="rownote">${CH.esc(fun.note || '')}</p>
</section>

<section class="vizcard"><h3>5 · What that does to your design</h3>
  <p class="vizsub">alpha ${CH.esc(d.design.alpha)} · target power ${CH.pct(d.design.target_power)} · Schoenfeld, 1:1 allocation${withParticipants ? ` · event probability ${CH.num(d.design.event_probability)}` : ''}.</p>
  <table class="datatable"><thead><tr><th>Basis</th><th>HR</th><th>Events needed</th>${withParticipants ? '<th>Participants</th>' : ''}<th>Power delivered</th></tr></thead><tbody>
  ${rows.map(r => `<tr${r.label === 'Registry-aware estimate' ? ' class="highlight"' : ''}><td>${CH.esc(r.label)}</td>
    <td>${r.hazard_ratio === r.hazard_ratio ? CH.num(r.hazard_ratio) : '--'}</td>
    <td>${r.required_events ? CH.int(r.required_events) : '<span class="rownote">not feasible</span>'}</td>
    ${withParticipants ? `<td>${r.required_participants ? CH.int(r.required_participants) : '--'}</td>` : ''}
    <td>${r.power_at_planned_events != null ? CH.pct(r.power_at_planned_events) : '--'}</td></tr>`).join('')}
  </tbody></table>
  ${con ? `<div class="meterrow">
     ${meter(d.design.target_power, null, 'Power you designed for')}
     ${meter(con.delivered_power_if_registry_aware_is_true, d.design.target_power, 'Power actually delivered', `if the registry-aware estimate is closer to the truth`)}
   </div><p class="viznote">${CH.esc(con.summary)}</p>` : ''}
</section>

<div class="vizgrid">
  <section class="vizcard"><h3>6 · If the unknown trials were known</h3>
    <p class="vizsub">${CH.int(sens.unknown_trials)} trials have neither a publication nor a posted result. Their effect is assumed, not imputed.</p>
    ${sens.points && sens.points.length ? linechart(
      sens.points.map(pt => ({y: pt.pooled_hazard_ratio,
        label: `assume HR ${CH.num(pt.assumed_hazard_ratio_for_unknowns)} → pooled HR ${CH.num(pt.pooled_hazard_ratio, 3)}${pt.required_events ? `, ${CH.int(pt.required_events)} events` : ', not feasible'}`})),
      {title: 'sensitivity sweep', xlo: `assume HR ${CH.num(sens.points[0].assumed_hazard_ratio_for_unknowns)}`, xhi: `HR ${CH.num(sens.points[sens.points.length - 1].assumed_hazard_ratio_for_unknowns)}`}) : ''}
    <p class="rownote">${CH.esc(sens.note || '')}</p>
  </section>

  <section class="vizcard"><h3>7 · Does the correction actually help?</h3>
    ${back.ran ? `<p class="vizsub">Leave-one-out over ${back.n} trials, ${CH.pct(back.level)} prediction interval.</p>
    <table class="datatable"><thead><tr><th>Model</th><th>Coverage</th><th>MAE log(HR)</th><th>Bias</th></tr></thead><tbody>
    ${[['literature_only', 'Literature-only'], ['registry_aware', 'Registry-aware']].map(([k, label]) => {
      const b = back.summary[k] || {};
      return `<tr><td>${label}</td><td>${b.n ? CH.pct(b.coverage) : '--'}</td><td>${b.n ? CH.num(b.mean_absolute_error_log_hr, 3) : '--'}</td><td>${b.n ? (b.bias_log_hr > 0 ? '+' : '') + CH.num(b.bias_log_hr, 3) : '--'}</td></tr>`;
    }).join('')}</tbody></table>
    <p class="viznote">${CH.esc(back.verdict)}</p>` : `<p class="empty">${CH.esc(back.note || 'Back-test did not run.')}</p>`}
  </section>
</div>

<section class="vizcard" id="overviewcard"><h3>8 · Does it repeat in other disease areas?</h3><p class="vizsub">Loading the other saved cohorts…</p></section>

${recoveryPanel(d)}

<section class="vizcard" id="ledgercard"><h3>10 · What the model layer cost</h3><p class="vizsub">Loading the ledger…</p></section>

<details class="methods"><summary>How these numbers were produced</summary>
  ${d.guardrails.map(g => `<p>· ${CH.esc(g)}</p>`).join('')}
  <p>${CH.esc(d.design.method)}</p><p>${CH.esc(back.method || '')}</p>
</details>`;
}

function recoveryPanel(d) {
  const r = d.recovery, src = d.evidence_sources || {};
  const sourcing = `<p class="rownote">Pooled estimates by source: ${CH.int(src.registry_posted)} posted in the registry · ${CH.int(src.publication_extracted)} extracted from open full text.</p>`;
  if (!r) return `<section class="vizcard"><h3>9 · Reading the papers the registry left out</h3>
    <p class="vizsub">Most trials without a usable estimate do have a publication. Tick <b>Read open full text</b> to recover hazard ratios from Europe PMC, with a small model reading only the sentences that could carry one.</p>${sourcing}</section>`;
  return `<section class="vizcard"><h3>9 · Reading the papers the registry left out</h3>
  <p class="vizsub">${CH.int(r.candidates)} trials had a publication but no usable estimate · ${CH.int(r.with_full_text)} had open full text · ${CH.int(r.papers_read)} read · ${CH.int(r.trials_recovered)} recovered for this endpoint${r.trials_recovered_other_endpoint ? `, ${CH.int(r.trials_recovered_other_endpoint)} for the other` : ''}.</p>
  ${sourcing}
  <div class="vizgrid">
    <div>${meter(r.token_reduction || 0, null, 'Model input avoided', `${CH.int(r.tokens_measured)} tokens spent vs ${CH.int(r.tokens_if_whole_papers)} if whole papers had been sent`)}</div>
    <div class="chartlabels"><div class="chartrow"><span class="chip" style="background:${VIZ.good}"></span><span class="rowlabel">Answered by the small model</span><b>${CH.int(r.tier_counts.small)}</b></div>
      <div class="chartrow"><span class="chip" style="background:${VIZ.accent}"></span><span class="rowlabel">Escalated to the larger model</span><b>${CH.int(r.tier_counts.large)}</b></div>
      <div class="chartrow"><span class="chip" style="background:${VIZ.context}"></span><span class="rowlabel">Served from cache</span><b>${CH.int(r.tier_counts.cached)}</b></div></div>
  </div>
  ${(r.recovered || []).length ? `<table class="datatable"><thead><tr><th>Trial</th><th>Endpoint</th><th>HR (95% CI)</th><th>Read from</th></tr></thead><tbody>
    ${r.recovered.slice(0, 8).map(x => { const e = x.estimates[0]; return `<tr><td>${CH.esc(x.nct_id)}</td><td>${CH.esc(e.endpoint.toUpperCase())}</td><td>${CH.num(e.hazard_ratio)} (${CH.num(e.ci_lower)}–${CH.num(e.ci_upper)})</td><td><a href="https://europepmc.org/article/PMC/${CH.esc(x.pmcid)}" target="_blank" rel="noreferrer">${CH.esc(x.pmcid)} ↗</a> · ${x.sentences_sent} sentences</td></tr>`; }).join('')}
  </tbody></table>` : ''}
  <p class="rownote">Every extracted value was checked against the sentence it came from before being kept: the ratio must be positive, the interval must bracket it, and the quoted evidence must appear in the text. Recovered trials join the published arm by construction; the registry-only arm cannot be rescued from the literature.</p>
</section>`;
}

// --- Across disease areas -----------------------------------------------------

async function loadOverview() {
  try { overview = await callJSON('/api/overview'); renderOverview(); }
  catch (e) { const el = $('#overviewcard'); if (el) el.innerHTML = `<h3>8 · Does it repeat in other disease areas?</h3><p class="empty">${CH.esc(e.message)}</p>`; }
}

function renderOverview() {
  const el = $('#overviewcard'); if (!el || !overview) return;
  const rows = overview.cohorts || [], pat = overview.pattern || {};
  const current = design && design.cohort ? `${design.cohort.condition}|${design.cohort.endpoint_class}` : '';
  const fmtHR = b => b && b.hazard_ratio ? CH.num(b.hazard_ratio) : '--';
  el.innerHTML = `<h3>8 · Does it repeat in other disease areas?</h3>
  <p class="vizsub">Every saved cohort, run through the same pipeline. Significant trials were linked to a publication more often in ${CH.int(pat.significant_linked_more_often_in)} of ${CH.int(pat.cohorts_compared)} cohorts; adding registry-only trials moved the prior toward the null in ${CH.int(pat.prior_moved_toward_null_in)} of ${CH.int(pat.cohorts_with_registry_only_trials)}.</p>
  ${rows.length ? `<table class="datatable"><thead><tr><th>Cohort</th><th>Trials</th><th>Linked · significant</th><th>Linked · not sig.</th><th>HR literature → registry</th><th>Egger intercept</th></tr></thead><tbody>
  ${rows.map(r => { const l = r.linkage || {}, sg = l.significant || {}, ns = l.not_significant || {}, e = (r.egger || {}).literature_only || {};
    const isCurrent = `${r.condition}|${r.endpoint_class}` === current;
    return `<tr${isCurrent ? ' class="highlight"' : ''}><td><button class="linklike" data-cohort="${CH.esc(r.condition)}" data-endpoint="${CH.esc(r.endpoint_class)}">${CH.esc(r.condition)}</button> <span class="rownote">${CH.esc((r.endpoint_class || '').toUpperCase())}</span></td><td>${CH.int(r.trials)}</td><td>${sg.n ? `${CH.pct(sg.linkage_rate)} <span class="rownote">n=${CH.int(sg.n)}</span>` : '--'}</td><td>${ns.n ? `${CH.pct(ns.linkage_rate)} <span class="rownote">n=${CH.int(ns.n)}</span>` : '--'}</td><td>${fmtHR(r.priors.literature_only)} → ${fmtHR(r.priors.registry_aware)} <span class="rownote">+${CH.int(r.priors.trials_added)} trials</span></td><td>${e.ran ? (e.intercept > 0 ? '+' : '') + CH.num(e.intercept) + (e.p_value != null && e.p_value < 0.05 ? ' *' : '') : '--'}</td></tr>`; }).join('')}
  </tbody></table>` : '<p class="empty">No saved cohorts yet. Run any disease area above and it is kept.</p>'}
  <p class="rownote">${CH.esc(overview.note || '')} Click a cohort to load it. * Egger p &lt; 0.05.</p>`;
  document.querySelectorAll('[data-cohort]').forEach(b => b.onclick = () => {
    $('#condition').value = b.dataset.cohort; $('#endpoint').value = b.dataset.endpoint; runDesign();
  });
}

// --- Model spend ----------------------------------------------------------------

async function loadLedger() {
  try { ledger = await callJSON('/api/llm-ledger'); renderLedger(); }
  catch (e) { const el = $('#ledgercard'); if (el) el.innerHTML = `<h3>10 · What the model layer cost</h3><p class="empty">${CH.esc(e.message)}</p>`; }
}

function renderLedger() {
  const el = $('#ledgercard'); if (!el || !ledger) return;
  const l = ledger, cache = l.cache || {}, budget = l.budget || {};
  const usd = v => v == null ? '--' : '$' + Number(v).toFixed(v < 0.1 ? 4 : 2);
  const purposes = Object.entries(l.by_purpose || {}).sort((a, b) => b[1].prompt_tokens + b[1].completion_tokens - a[1].prompt_tokens - a[1].completion_tokens);
  const PURPOSE = {recover: 'Reading hazard ratios from full text', adjudicate: 'Judging whether a paper reports a trial', baseline_whole_paper: 'One whole paper, measured as the baseline', smoke: 'Connectivity check'};
  el.innerHTML = `<h3>10 · What the model layer cost</h3>
  <p class="vizsub">Every call ever made, from the ledger the client writes. Tokens are the API's own usage counts; prices are list prices for ${CH.esc((l.tiers || {}).small || '')} and ${CH.esc((l.tiers || {}).large || '')}.</p>
  <div class="stats ledgerstats">
    <div class="stat"><b>${usd(l.cost_usd)}</b><span><strong>Spent in total</strong><br>${CH.int(l.calls)} paid calls · ${CH.int(l.total_tokens)} tokens</span></div>
    <div class="stat"><b>${usd(l.cost_usd_if_all_large_tier)}</b><span><strong>Same work at the larger tier</strong><br>what "small model first" avoided</span></div>
    <div class="stat"><b>${CH.int(cache.hits_this_process)}</b><span><strong>Answered from cache</strong><br>${CH.int(cache.tokens_avoided_this_process)} tokens not re-sent this session</span></div>
    <div class="stat"><b>${CH.int(budget.calls_this_process)} / ${CH.int(budget.max_calls)}</b><span><strong>Budget used</strong><br>hard cap on paid calls per process</span></div>
  </div>
  ${purposes.length ? hbar(purposes.map(([k, v]) => ({label: PURPOSE[k] || k, value: v.prompt_tokens + v.completion_tokens, display: CH.int(v.prompt_tokens + v.completion_tokens) + ' tokens', note: `${CH.int(v.calls)} calls · ${usd(v.cost_usd)}`, color: k === 'baseline_whole_paper' ? VIZ.context : VIZ.accent})), {title: 'tokens by purpose'}) : '<p class="empty">No model calls have been made yet.</p>'}
  <p class="rownote">Four things keep this small: the model reads sentences, never papers; the smallest tier answers first and the larger one is consulted only when validation fails; identical requests are served from a disk cache; and a hard cap refuses rather than overspends.</p>`;
}

// --- Cascade: candidates for a trial with no identifier link ----------------

async function runCandidates(nct) {
  if (busy) return; busy = true;
  message('Retrieving candidate papers from the index, scoring them, and sending only the unclear ones to a small model…');
  try {
    candidates = await callJSON('/api/candidates?' + new URLSearchParams({nct}));
    renderCandidates(); message('');
  } catch (e) { message(e.message, true); }
  finally { busy = false; }
}

const DECISION = {
  accepted: ['ok', 'Accepted by score'], accepted_by_adjudication: ['ok', 'Accepted · model-assisted'],
  review: ['warn', 'Needs a human'], rejected_by_adjudication: ['muted', 'Rejected · model-assisted'], rejected: ['muted', 'Rejected by score'],
};

function renderCandidates() {
  const c = candidates, t = c.trial;
  const el = $('#cascadecard'); if (!el) return;
  if (c.retrieval === 'unavailable') { el.innerHTML = `<h3>Papers the identifiers missed</h3><p class="empty">Candidate search is unavailable: ${CH.esc(c.error || 'Elasticsearch not reachable')}.</p>`; return; }
  el.innerHTML = `<h3>Papers the identifiers missed</h3>
  <p class="vizsub">Keyword retrieval over the index → deterministic score → a small model reads only the pairs between ${c.thresholds.reject_below} and ${c.thresholds.accept_at}. ${CH.int(c.llm_tokens)} model tokens spent on this trial.</p>
  ${c.candidates.length ? `<table class="datatable"><thead><tr><th>Paper</th><th>Score</th><th>Decision</th><th>Why</th></tr></thead><tbody>
  ${c.candidates.map(x => { const [tone, word] = DECISION[x.decision] || ['muted', x.decision];
    const why = x.llm && x.llm.reason ? `<i>${CH.esc(x.llm.model)}:</i> ${CH.esc(x.llm.reason)}` : CH.esc((x.match.reasons || [])[0] || '');
    return `<tr><td>${CH.esc(x.title)}<br><span class="rownote">${x.year || ''} · PMID ${CH.esc(x.pmid || '')}</span></td><td>${CH.num(x.match.score)}</td><td><span class="tag ${tone}">${word}</span></td><td class="rownote">${why}</td></tr>`; }).join('')}
  </tbody></table>` : '<p class="empty">No candidates retrieved.</p>'}
  <p class="rownote">${CH.esc(c.note)}</p>`;
}

// --- Free-text search over the index ---------------------------------------

let searchFilters = {};
async function runSearch() {
  if (!guard('runsearch', 'Searching the index…')) return;
  try {
    const params = {q: $('#q').value, size: 15, kind: $('#kind') ? $('#kind').value : ''};
    Object.entries(searchFilters).forEach(([k, v]) => { params[k] = String(v); });
    searchResult = await callJSON('/api/search?' + new URLSearchParams(params)); renderSearch(); message('');
  }
  catch (e) { message(e.message, true); }
  finally { release('runsearch'); }
}

const FACET_LABELS = {
  has_publication: {title: 'Publication identified', values: {true: 'yes', false: 'no'}},
  posted_hazard_ratio: {title: 'Posted a hazard ratio', values: {true: 'yes', false: 'no'}},
  phases: {title: 'Phase', values: {PHASE1: '1', PHASE2: '2', PHASE3: '3', PHASE4: '4', EARLY_PHASE1: 'early 1', NA: 'n/a'}},
  sponsor_class: {title: 'Sponsor', values: {INDUSTRY: 'industry', NIH: 'NIH', OTHER: 'other', OTHER_GOV: 'government', NETWORK: 'network', FED: 'federal'}},
  is_retracted: {title: 'Retracted', values: {true: 'yes', false: 'no'}},
};

function facetBar(r) {
  const f = r.facets || {};
  const groups = Object.keys(FACET_LABELS).filter(k => (f[k] || []).length);
  if (!groups.length) return '';
  return `<div class="facets">${groups.map(k => `<div class="facetgroup"><span class="eyebrow">${CH.esc(FACET_LABELS[k].title)}</span>${f[k].map(b => {
    const active = String((r.filters || {})[k]) === String(b.value);
    return `<button class="facet${active ? ' active' : ''}" data-facet="${CH.esc(k)}" data-value="${CH.esc(String(b.value))}">${CH.esc(FACET_LABELS[k].values[String(b.value)] || String(b.value))} <b>${CH.int(b.count)}</b></button>`; }).join('')}</div>`).join('')}
  ${Object.keys(r.filters || {}).length ? '<button class="facet clear" data-facet="" data-value="">× clear filters</button>' : ''}</div>`;
}

function renderSearch() {
  const r = searchResult;
  $('#searchpanel').innerHTML = `<div class="sectionhead"><div><span class="eyebrow">EVIDENCE INDEX</span><h2>“${CH.esc(r.query)}”</h2></div><div class="sourcepill">● ${r.total != null ? CH.int(r.total) + ' matches in ' : ''}${CH.int((r.index || {})['trialtrace-trials'])} trials · ${CH.int((r.index || {})['trialtrace-works'])} papers indexed</div></div>
  ${facetBar(r)}
  <div class="publist">${r.hits.map(h => { const isTrial = h._index && h._index.endsWith('trials'); const hl = h._highlight ? Object.values(h._highlight).flat()[0] : '';
    return `<button class="paperrow" data-open="${isTrial ? 'trial:' + CH.esc(h.nct_id) : 'doi:' + CH.esc(h.doi || '')}"><i style="background:${isTrial ? VIZ.good : VIZ.accent};flex-shrink:0"></i><div>${CH.esc(h.title)}<span>${isTrial ? CH.esc(h.nct_id) + ' · ' + CH.esc((h.phases || []).join('/')) : (h.journal ? CH.esc(h.journal) + ' · ' : '') + (h.year || '')} · score ${CH.num(h._score, 1)}</span>${hl ? `<span class="hl">${hl}</span>` : ''}</div></button>`; }).join('') || '<p class="empty">No hits.</p>'}</div>
  <p class="rownote">Hits are keyword matches over titles, abstracts, conditions, interventions and authors; highlighted text shows what matched. The counts above are aggregations over every match, not only the page shown: search a drug and read off how many of its completed trials have a publication. This is the same retrieval that proposes candidates when a trial has no identifier link.</p>`;
  document.querySelectorAll('[data-facet]').forEach(el => el.onclick = () => {
    const k = el.dataset.facet, v = el.dataset.value;
    if (!k) searchFilters = {};
    else if (String(searchFilters[k]) === v) delete searchFilters[k];
    else searchFilters[k] = v;
    runSearch();
  });
  document.querySelectorAll('[data-open]').forEach(el => el.onclick = () => {
    const [kind, value] = el.dataset.open.split(/:(.+)/);
    if (kind === 'trial' && value) { $('#nct').value = value; setMode('trial'); runTrial(); }
    else if (kind === 'doi' && value) { $('#doi').value = value; setMode('sources'); checkSources(); }
  });
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
<section class="vizcard" id="cascadecard"><h3>Papers the identifiers missed</h3><p class="vizsub">Identifier channels find what declares the trial. This searches the index for papers that might report it without saying so, scores them, and asks a small model only about the unclear ones.</p><button class="external" id="findcandidates">⌕ Search for unlinked publications</button></section>
<details class="methods"><summary>Sources</summary><p><a href="${CH.esc(t.url)}" target="_blank" rel="noreferrer">${CH.esc(t.nct_id)} on ClinicalTrials.gov ↗</a></p><p>${CH.esc(trial.sampling)}</p></details>`;

  const fc = $('#findcandidates'); if (fc) fc.onclick = () => runCandidates(t.nct_id);
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
