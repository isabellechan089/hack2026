// Loads the page scripts into a DOM stub, drives every mode the way a user
// would, and prints one "key=value" line per assertion for the Python test.
//
// This exists because neither a syntax check nor an id cross-reference catches
// a handler that runs and then does the wrong thing -- which is exactly how the
// mode switch once ended up calling itself instead of loading the graph.
ObjC.import("Foundation");
function read(p){ return $.NSString.stringWithContentsOfFileEncodingError(p, $.NSUTF8StringEncoding, null).js; }
var REPO = $.NSProcessInfo.processInfo.environment.objectForKey('REPO').js;
var F = REPO + '/tests/frontend/';

var out = [];
try {
  var fn = new Function('FIX', 'OUT',
    read(F + 'dom_stub.js') + read(REPO + '/static/charts.js') + read(REPO + '/static/views.js')
    + read(REPO + '/static/app.js') + `
    var q = document.querySelector.bind(document);
    function has(id, re){ return re.test(q(id).innerHTML); }

    OUT.push('initial_mode=' + mode);
    OUT.push('start_designpanel_visible=' + (q('#designpanel').hidden === false));
    OUT.push('start_workspace_hidden=' + (q('#workspace').hidden === true));
    OUT.push('start_sourcepanel_hidden=' + (q('#sourcepanel').hidden === true));

    q('#modesources').onclick();
    OUT.push('sources_mode_switch=' + (mode === 'sources' && q('#sourcepanel').hidden === false));

    sources = FIX.sources; renderSources();
    OUT.push('sources_rendered=' + (q('#sourcepanel').innerHTML.length > 500));
    OUT.push('sources_has_flagcard=' + has('#sourcepanel', /flagcard/));
    OUT.push('sources_names_retraction=' + has('#sourcepanel', /retracted/i));
    OUT.push('sources_has_trace_link=' + has('#sourcepanel', /data-trace/));

    q('#modetrace').onclick();
    OUT.push('trace_mode_is_trace=' + (mode === 'trace'));
    OUT.push('trace_shows_workspace=' + (q('#workspace').hidden === false));
    OUT.push('trace_hides_sourcepanel=' + (q('#sourcepanel').hidden === true));
    data = FIX.demo; selected = data.seed; render();
    OUT.push('graph_nodes_drawn=' + ((q('#graph').innerHTML.match(/<circle/g) || []).length > 10));
    OUT.push('graph_edges_drawn=' + ((q('#graph').innerHTML.match(/class="edge/g) || []).length > 10));
    OUT.push('stat_tiles=' + ((q('#stats').innerHTML.match(/class="stat"/g) || []).length));
    OUT.push('coverage_shown=' + /showing \\d+ of \\d+/.test(q('#coverage').textContent));
    OUT.push('seed_has_no_recenter=' + (has('#details', /id="recenter"/) === false));
    var other = data.nodes.find(function(n){ return n.id !== data.seed && n.doi; });
    select(other.id);
    OUT.push('node_offers_recenter=' + has('#details', /id="recenter"/));
    OUT.push('node_offers_checkrefs=' + has('#details', /id="checkrefs"/));
    OUT.push('node_shows_evidence_trail=' + has('#details', /EVIDENCE TRAIL/));

    q('#modedesign').onclick();
    OUT.push('design_mode=' + (mode === 'design'));
    OUT.push('design_panel_visible=' + (q('#designpanel').hidden === false));
    OUT.push('design_line_visible=' + (q('#lineDesign').hidden === false));
    design = FIX.design; renderDesign();
    OUT.push('design_has_stackbar=' + has('#designpanel', /class="chart stack"/));
    OUT.push('design_has_linkage_bars=' + has('#designpanel', /Statistically significant/));
    OUT.push('design_has_forest=' + has('#designpanel', /class="chart forest"/));
    OUT.push('design_has_meters=' + has('#designpanel', /class="meterfill"/));
    OUT.push('design_has_backtest=' + has('#designpanel', /Coverage/));
    OUT.push('design_has_sensitivity=' + has('#designpanel', /unknown trials|neither a publication/));
    OUT.push('design_no_undefined=' + (has('#designpanel', /undefined|NaN/) === false));
    OUT.push('design_has_funnel=' + has('#designpanel', /class="chart funnel"/));
    OUT.push('design_funnel_has_points=' + ((q('#designpanel').innerHTML.match(/<circle cx=/g) || []).length > 20));
    OUT.push('design_has_egger=' + has('#designpanel', /Egger/));
    OUT.push('design_has_reading_guide=' + has('#designpanel', /How to read this page/));
    OUT.push('guide_explains_the_correction=' + has('#designpanel', /hazard ratio below 1 favours/i));
    OUT.push('guide_quotes_this_cohort=' + has('#designpanel', /non-small cell lung cancer trial that posted results/));
    OUT.push('charts_label_a_scale=' + ((q('#designpanel').innerHTML.match(/<text /g) || []).length > 8));
    OUT.push('forest_marks_the_null=' + has('#designpanel', /no difference at HR 1\.0/));
    OUT.push('bars_are_not_stretched=' + ((q('#designpanel').innerHTML.match(/preserveAspectRatio="none"/g) || []).length === 1));
    OUT.push('design_names_provenance=' + has('#designpanel', /registrations from ClinicalTrials\\.gov/));
    OUT.push('design_has_participants=' + has('#designpanel', /<th>Participants<\\/th>/));
    OUT.push('design_has_lazy_cards=' + (has('#designpanel', /id="overviewcard"/) && has('#designpanel', /id="ledgercard"/)));
    overview = FIX.overview; renderOverview();
    OUT.push('overview_lists_cohorts=' + ((q('#overviewcard').innerHTML.match(/data-cohort=/g) || []).length >= 2));
    OUT.push('overview_states_pattern=' + has('#overviewcard', /more often in \\d+ of \\d+ cohorts/));
    OUT.push('overview_no_undefined=' + (has('#overviewcard', /undefined|NaN/) === false));
    ledger = FIX.ledger; renderLedger();
    OUT.push('ledger_shows_dollars=' + has('#ledgercard', /\\$\\d/));
    OUT.push('ledger_shows_counterfactual=' + has('#ledgercard', /Same work at the larger tier/));
    OUT.push('ledger_has_purpose_bars=' + has('#ledgercard', /tokens by purpose/));
    OUT.push('ledger_no_undefined=' + (has('#ledgercard', /undefined|NaN/) === false));

    q('#modereviewer').onclick();
    OUT.push('reviewer_mode=' + (mode === 'reviewer'));
    OUT.push('reviewer_panel_visible=' + (q('#reviewerpanel').hidden === false));
    reviewer = FIX.reviewer; renderReviewer();
    OUT.push('reviewer_has_verdict=' + has('#reviewerpanel', /class="verdict/));
    OUT.push('reviewer_has_path=' + has('#reviewerpanel', /pathchain/));
    OUT.push('reviewer_has_evidence=' + has('#reviewerpanel', /shared work/));
    OUT.push('reviewer_no_undefined=' + (has('#reviewerpanel', /undefined|NaN/) === false));

    q('#modetrial').onclick();
    OUT.push('trial_mode=' + (mode === 'trial'));
    OUT.push('trial_panel_visible=' + (q('#trialpanel').hidden === false));
    trial = FIX.trial; renderTrial();
    OUT.push('trial_has_publist=' + has('#trialpanel', /data-pub=/));
    OUT.push('trial_has_table=' + has('#trialpanel', /class="datatable"/));
    OUT.push('trial_has_status_tags=' + has('#trialpanel', /class="tag /));
    OUT.push('trial_no_undefined=' + (has('#trialpanel', /undefined|NaN/) === false));

    // recovery / token panel inside the design view (fixture captured with recover=1)
    OUT.push('design_has_recovery_panel=' + has('#designpanel', /Reading the papers the registry left out/));
    OUT.push('design_recovery_has_meter=' + has('#designpanel', /Model input avoided/));
    OUT.push('design_recovery_lists_trials=' + has('#designpanel', /europepmc\\.org\\/article\\/PMC/));
    OUT.push('design_names_sources=' + has('#designpanel', /extracted from open full text/));

    // cascade card inside the trial view, then render captured candidates into it
    q('#modetrial').onclick();
    OUT.push('trial_has_cascade_card=' + has('#trialpanel', /id="cascadecard"/));
    candidates = FIX.candidates; renderCandidates();
    OUT.push('cascade_renders_decisions=' + has('#cascadecard', /Rejected · model-assisted|Accepted · model-assisted|Needs a human/));
    OUT.push('cascade_shows_model_reason=' + has('#cascadecard', /<i>gpt/));
    OUT.push('cascade_never_shows_plain_accepted=' + (has('#cascadecard', /Accepted by score/) === false));
    OUT.push('cascade_no_undefined=' + (has('#cascadecard', /undefined|NaN/) === false));

    q('#modesearch').onclick();
    OUT.push('search_mode=' + (mode === 'search'));
    OUT.push('search_panel_visible=' + (q('#searchpanel').hidden === false));
    OUT.push('search_line_visible=' + (q('#lineSearch').hidden === false));
    searchResult = FIX.search; renderSearch();
    OUT.push('search_has_hits=' + ((q('#searchpanel').innerHTML.match(/data-open=/g) || []).length > 3));
    OUT.push('search_shows_index_size=' + has('#searchpanel', /papers indexed/));
    OUT.push('search_has_facets=' + has('#searchpanel', /class="facets"/));
    OUT.push('search_facet_publication=' + has('#searchpanel', /Publication identified/));
    OUT.push('search_shows_total=' + has('#searchpanel', /\\d+ matches in/));
    OUT.push('search_no_undefined=' + (has('#searchpanel', /undefined|NaN/) === false));

    q('#modesources').onclick();
    OUT.push('back_to_sources=' + (q('#sourcepanel').hidden === false && q('#designpanel').hidden === true
                                   && q('#workspace').hidden === true && q('#trialpanel').hidden === true));
    return OUT;
  `);
  out = fn({
    demo: JSON.parse(read(F + 'demo.json')),
    sources: JSON.parse(read(F + 'demo_sources.json')),
    design: JSON.parse(read(F + 'design.json')),
    reviewer: JSON.parse(read(F + 'reviewer.json')),
    trial: JSON.parse(read(F + 'trial.json')),
    candidates: JSON.parse(read(F + 'candidates.json')),
    search: JSON.parse(read(F + 'search.json')),
    overview: JSON.parse(read(F + 'overview.json')),
    ledger: JSON.parse(read(F + 'ledger.json')),
  }, []);
} catch (e) {
  out.push('THREW=' + (e && e.message));
}
out.join('\n');
