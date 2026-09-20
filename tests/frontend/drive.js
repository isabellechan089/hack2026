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
    OUT.push('start_sourcepanel_visible=' + (q('#sourcepanel').hidden === false));
    OUT.push('start_workspace_hidden=' + (q('#workspace').hidden === true));

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
  }, []);
} catch (e) {
  out.push('THREW=' + (e && e.message));
}
out.join('\n');
