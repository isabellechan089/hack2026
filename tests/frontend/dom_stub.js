// Minimal DOM + fetch stub so app.js can actually be executed and its two
// modes driven, to catch runtime errors a syntax check cannot see.
var LOG = [];
function log(s){ LOG.push(s); }

function makeEl(id){
  return {
    id: id, _html: '', textContent: '', value: '', hidden: false, disabled: false,
    className: '', open: false, dataset: {},
    get innerHTML(){ return this._html; },
    set innerHTML(v){ this._html = String(v); },
    classList: { toggle: function(){}, add: function(){}, remove: function(){}, contains: function(){return false;} },
    onclick: null, onsubmit: null, onchange: null, oninput: null,
    onpointermove: null, onpointerdown: null, onpointerup: null, onpointercancel: null,
    onkeydown: null,
    showModal: function(){ this.open = true; }, close: function(){ this.open = false; },
    scrollIntoView: function(){}, setPointerCapture: function(){},
    getBoundingClientRect: function(){ return {width: 900, height: 570, left:0, top:0}; },
    closest: function(){ return null; },
    querySelectorAll: function(){ return []; },
  };
}
var ELS = {};
var document = {
  querySelector: function(sel){
    var id = sel.replace('#','');
    if(!ELS[id]) ELS[id] = makeEl(id);
    return ELS[id];
  },
  querySelectorAll: function(sel){
    // Collect data-* nodes the app wires up after rendering.
    var out = [];
    var src = (ELS.details ? ELS.details._html : '') + (ELS.sourcepanel ? ELS.sourcepanel._html : '')
            + (ELS.paperlist ? ELS.paperlist._html : '') + (ELS.graph ? ELS.graph._html : '');
    var attr = sel.replace('[','').replace(']','');
    var re = new RegExp(attr + '="([^"]*)"', 'g'), m;
    while((m = re.exec(src))){ var e = makeEl('dyn'); e.dataset = {}; 
      e.dataset[attr.replace('data-','')] = m[1]; out.push(e); }
    return out;
  },
  createElement: function(){ return makeEl('a'); },
};
var window = {};
var URL = { createObjectURL: function(){ return 'blob:x'; }, revokeObjectURL: function(){} };
function Blob(){}
function setTimeout(fn){ return 0; }

function URLSearchParams(o){ this.o=o||{}; }
URLSearchParams.prototype.toString=function(){ var p=[]; for(var k in this.o) p.push(k+'='+encodeURIComponent(this.o[k])); return p.join('&'); };
var FIXTURES = {};
function fetch(url){
  var key = url.split('?')[0];
  if(FIXTURES[key] === undefined){
    return Promise.resolve({ ok:false, json: function(){ return Promise.resolve({error:'Not found'}); } });
  }
  return Promise.resolve({ ok:true, json: function(){ return Promise.resolve(FIXTURES[key]); } });
}
