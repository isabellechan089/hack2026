// Loads static/app.js inside the DOM stub, drives it the way a user would, and
// prints one "key=value" line per assertion for the Python test to check.
//
// This exists because neither a syntax check nor an id cross-reference catches
// a handler that runs but does the wrong thing -- which is exactly how the mode
// switch once ended up calling itself instead of loading the graph.
ObjC.import("Foundation");
function read(p){ return $.NSString.stringWithContentsOfFileEncodingError(p, $.NSUTF8StringEncoding, null).js; }
var REPO = $.NSProcessInfo.processInfo.environment.objectForKey('REPO').js;

var out = [];
try {
  var fn = new Function('DEMO_JSON', 'SOURCES_JSON', 'OUT',
    read(REPO + '/tests/frontend/dom_stub.js') + read(REPO + '/static/app.js') + `
    var q = document.querySelector.bind(document);
    OUT.push('initial_mode=' + mode);
    OUT.push('start_sourcepanel_visible=' + (q('#sourcepanel').hidden === false));
    OUT.push('start_workspace_hidden=' + (q('#workspace').hidden === true));

    sources = JSON.parse(SOURCES_JSON);
    renderSources();
    OUT.push('sources_rendered=' + (q('#sourcepanel').innerHTML.length > 500));
    OUT.push('sources_has_flagcard=' + /flagcard/.test(q('#sourcepanel').innerHTML));
    OUT.push('sources_has_trace_link=' + /data-trace/.test(q('#sourcepanel').innerHTML));
    OUT.push('sources_names_retraction=' + /retracted/i.test(q('#sourcepanel').innerHTML));

    q('#modetrace').onclick();
    OUT.push('trace_shows_workspace=' + (q('#workspace').hidden === false));
    OUT.push('trace_hides_sourcepanel=' + (q('#sourcepanel').hidden === true));
    OUT.push('trace_mode_is_trace=' + (mode === 'trace'));

    data = JSON.parse(DEMO_JSON); selected = data.seed; render();
    OUT.push('graph_nodes_drawn=' + ((q('#graph').innerHTML.match(/<circle/g) || []).length > 10));
    OUT.push('graph_edges_drawn=' + ((q('#graph').innerHTML.match(/class="edge/g) || []).length > 10));
    OUT.push('stat_tiles=' + ((q('#stats').innerHTML.match(/class="stat"/g) || []).length));
    OUT.push('coverage_shown=' + /showing \\d+ of \\d+/.test(q('#coverage').textContent));
    OUT.push('seed_has_no_recenter=' + (/id="recenter"/.test(q('#details').innerHTML) === false));

    var other = data.nodes.find(function(n){ return n.id !== data.seed && n.doi; });
    select(other.id);
    OUT.push('node_offers_recenter=' + /id="recenter"/.test(q('#details').innerHTML));
    OUT.push('node_offers_checkrefs=' + /id="checkrefs"/.test(q('#details').innerHTML));
    OUT.push('node_shows_evidence_trail=' + /EVIDENCE TRAIL/.test(q('#details').innerHTML));

    q('#modesources').onclick();
    OUT.push('back_to_sources=' + (q('#sourcepanel').hidden === false && q('#workspace').hidden === true));
    return OUT;
  `);
  out = fn(read(REPO + '/data/demo.json'), read(REPO + '/data/demo_sources.json'), []);
} catch (e) {
  out.push('THREW=' + (e && e.message));
}
out.join('\n');
