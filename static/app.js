const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let data,selected,zoom=1,offset={x:0,y:0},view='graph',busy=false,mode='sources',sources,design,reviewer,trial,searchResult,candidates;
const colors={retracted:'#b3392f',direct:'#d9722c',indirect:'#4a7fb5',none:'#93a49a'};
const VIZ={accent:'#d9722c',context:'#8d9d94',good:'#3f7d54',ink:'#213b38',muted:'#75827c',surface:'#ffffff',grid:'#e7ebe4'};
const statuses={retracted:'Retraction notice found',updated:'Update notice found',no_notice_found:'No notice found',screened:'Screened, not flagged',unknown:'Status unknown'};
const names={retracted:'Retracted paper',direct:'Direct citation connection',indirect:'Indirect citation connection',none:'No retraction path in sample'};
function message(text,error=false){$('#notice').textContent=text;$('#notice').className=error?'error':''}
async function load(demo=false){if(busy)return;busy=true;$('#explore').disabled=true;$('#demo').disabled=true;message(demo?'Loading the saved evidence snapshot…':'Tracing citations and checking update notices. This can take up to a few minutes…');try{const r=await fetch(demo?'/api/demo':'/api/graph?'+new URLSearchParams({doi:$('#doi').value,depth:$('#depth').value,limit:$('#breadth').value}));const result=await r.json();if(!r.ok)throw Error(result.error);data=result;selected=data.seed;zoom=1;offset={x:0,y:0};$('#filter').value='all';$('#find').value='';$('#doi').value=data.nodes.find(n=>n.id===data.seed).doi||$('#doi').value;render();message(data.warnings.join(' '),!!data.warnings.length)}catch(e){message(e.message||'Could not load this graph. Try the saved example.',true)}finally{busy=false;$('#explore').disabled=false;$('#demo').disabled=false}}
function render(){const count=k=>data.nodes.filter(n=>n.exposure===k).length;$('#stats').innerHTML=[[data.nodes.length,'Papers in this sample','Across '+data.depth+' citation hops'],[count('retracted'),'Retracted papers','Linked to source evidence'],[count('direct'),'Direct connections','Cite a retracted paper'],[(data.blast_radius&&data.blast_radius.cited_after_retraction!=null)?data.blast_radius.cited_after_retraction:count('indirect'),(data.blast_radius&&data.blast_radius.retraction_date)?'Cited after the retraction':'Indirect connections',(data.blast_radius&&data.blast_radius.retraction_date)?'Published after '+data.blast_radius.retraction_date:'Connected through other papers']].map(([v,t,s])=>`<div class="stat"><b>${v}</b><span><strong>${t}</strong><br>${s}</span></div>`).join('');$('#mode').textContent=(data.mode==='snapshot'?'● Saved real-data demo':'● Live lookup')+' · '+new Date(data.generated_at).toLocaleDateString();$('#sampling').textContent=data.sampling;$('#networkcount').textContent=data.nodes.length+' papers · '+data.edges.length+' citation links';
const cov=data.coverage;$('#coverage').textContent=cov&&cov.direct_citations_total?'showing '+cov.direct_citations_shown+' of '+cov.direct_citations_total+' direct citations':'';draw();details()}
function matching(n){return ($('#filter').value==='all'||n.exposure===$('#filter').value)&&n.title.toLowerCase().includes($('#find').value.toLowerCase())}
function positions(){let result={};const levels=[0,1,2];for(const level of levels){const nodes=data.nodes.filter(n=>n.distance===level);nodes.forEach((n,i)=>{if(level===0){result[n.id]={x:450,y:275};return}const angle=-Math.PI/2+i*2*Math.PI/nodes.length;const rx=level===1?175:345,ry=level===1?125:230;result[n.id]={x:450+Math.cos(angle)*rx,y:275+Math.sin(angle)*ry}})}return result}
function draw(){if(!data)return;const pos=positions(),node=data.nodes.find(n=>n.id===selected),path=node?.evidence_path||[],pathEdges=new Set(path.slice(0,-1).map((id,i)=>id+'|'+path[i+1]));const filtered=$('#filter').value!=='all'||$('#find').value;let svg='<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#9daa93"/></marker></defs><g id="scene" transform="translate('+offset.x+' '+offset.y+') translate(450 285) scale('+zoom+') translate(-450 -285)"><ellipse cx="450" cy="275" rx="175" ry="125" fill="none" stroke="#e4e9df" stroke-dasharray="4 6"/><ellipse cx="450" cy="275" rx="345" ry="230" fill="none" stroke="#e4e9df" stroke-dasharray="4 6"/>';
for(const e of data.edges){const a=pos[e.source],b=pos[e.target];if(!a||!b)continue;const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1,pad=e.target===data.seed?26:14;const dim=filtered&&(!matching(data.nodes.find(n=>n.id===e.source))||!matching(data.nodes.find(n=>n.id===e.target)));svg+=`<line class="edge ${pathEdges.has(e.source+'|'+e.target)?'path':''} ${dim?'dim':''}" x1="${a.x}" y1="${a.y}" x2="${b.x-dx/len*pad}" y2="${b.y-dy/len*pad}" marker-end="url(#arrow)"/>`}
data.nodes.forEach((n,i)=>{const p=pos[n.id];if(!p)return;const radius=n.id===data.seed?23:11+Math.min(5,Math.log10(n.citations+1));svg+=`<g class="node ${matching(n)?'':'dim'}" tabindex="0" role="button" aria-label="${esc(n.title)}" data-id="${esc(n.id)}" transform="translate(${p.x} ${p.y})"><title>${esc(n.title)} (${n.year}) — ${names[n.exposure]}</title>${selected===n.id?`<circle r="${radius+6}" fill="none" stroke="${colors[n.exposure]}" opacity=".35" stroke-width="2"/>`:''}<circle r="${radius}" fill="${colors[n.exposure]}" stroke="white" stroke-width="2"/><text text-anchor="middle" y="4" fill="white" font-size="${n.id===data.seed?14:9}" font-weight="700">${n.id===data.seed?'S':i}</text>${n.id===data.seed?'<text y="43" text-anchor="middle" font-size="10" fill="#607259">STARTING PAPER</text>':`<text y="${radius+14}" text-anchor="middle" font-size="9" fill="#71816c">${n.year||'—'}</text>`}</g>`});svg+='</g>';$('#graph').innerHTML=svg;
$('#paperlist').innerHTML=data.nodes.filter(matching).map(n=>`<button class="paperrow" data-id="${esc(n.id)}"><i style="background:${colors[n.exposure]};flex-shrink:0"></i><div>${esc(n.title)}<span>${n.year||'Year unavailable'} · ${names[n.exposure]}</span></div></button>`).join('')||'<p style="padding:20px">No matching papers. Try another filter.</p>';
document.querySelectorAll('[data-id]').forEach(el=>{el.onclick=()=>select(el.dataset.id);el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select(el.dataset.id)}}})}
function select(id){selected=id;draw();details()}
function doiLink(doi){return 'https://doi.org/'+encodeURI(String(doi).replace(/^https?:\/\/doi.org\//i,''))}
function details(){const n=data.nodes.find(n=>n.id===selected);const r=n.retraction;$('#details').innerHTML=`<div class="eyebrow">${n.id===data.seed?'STARTING PAPER':'PAPER DETAILS'}</div><span class="badge ${r.status==='retracted'?'':'neutral'}">${statuses[r.status]}</span><h3>${esc(n.title)}</h3><p class="authors">${esc(n.authors.join(', '))}</p><div class="metadata"><div><span>PUBLISHED</span><strong>${n.year||'Unknown'}</strong></div><div><span>CITATIONS · OPENALEX</span><strong>${n.citations.toLocaleString()}</strong></div><div style="grid-column:1/-1"><span>JOURNAL / SOURCE</span><strong>${esc(n.journal)}</strong></div></div><section class="detailsection"><h4>UPDATE EVIDENCE</h4>${r.notices.length?r.notices.map(v=>`<div class="evidencebox"><a href="${esc(doiLink(v.doi))}" target="_blank" rel="noreferrer">${esc(v.title)} ↗</a><p>${esc(v.type)} · ${v.date?esc(v.date.slice(0,10)):'Date unavailable'} · ${esc(v.source)}</p></div>`).join(''):`<p>${esc(r.reason||'No update notice returned by Crossref. This is not a guarantee of reliability.')}</p>`}${n.openalex_retracted&&r.status!=='retracted'?'<p>OpenAlex separately flags this work as retracted; Crossref did not confirm it in this lookup.</p>':''}<p>Crossref lookup · ${new Date(r.checked_at).toLocaleDateString()}</p></section><section class="detailsection"><h4>EVIDENCE TRAIL</h4><p>${n.exposure==='retracted'?'This paper has a linked retraction notice.':n.exposure==='none'?'No path to a confirmed retraction was found in this sampled graph.':names[n.exposure]+'. One shortest citation path is shown below.'}</p>${n.evidence_path.map((id,i)=>{const p=data.nodes.find(x=>x.id===id);return `${i?'<div class="patharrow">↓ cites</div>':''}<button class="pathitem" data-path="${esc(id)}"><b>${i+1}</b><span>${esc(p.title)}</span></button>`}).join('')}</section>${n.id!==data.seed&&n.doi?`<button class="external primaryish" id="recenter">◎ Make this the starting paper</button>`:''}${n.doi?`<button class="external" id="checkrefs">⌕ Check this paper's own references</button>`:''}${n.doi?`<a class="external" href="${esc(doiLink(n.doi))}" target="_blank" rel="noreferrer">Open publication ↗</a>`:''}<a class="external" href="${esc(n.id)}" target="_blank" rel="noreferrer">View OpenAlex record ↗</a>`;document.querySelectorAll('[data-path]').forEach(el=>el.onclick=()=>select(el.dataset.path));
const recenter=$('#recenter');if(recenter)recenter.onclick=()=>{$('#doi').value=n.doi;$('#depth').value='2';load()};
const refs=$('#checkrefs');if(refs)refs.onclick=()=>{$('#doi').value=n.doi;setMode('sources');checkSources()}}
const MODES={
 sources:{panel:'sourcepanel',line:'lineDoi',label:'PASTE A PAPER YOU ARE CITING, WRITING, OR REVIEWING',
   hint:'Screens every work this paper cites against OpenAlex and Crossref retraction notices',
   cta:'Check references',run:()=>checkSources(),has:()=>!!sources,seed:()=>checkSources(true)},
 trace:{panel:'workspace',line:'lineDoi',label:'START WITH A PAPER',
   hint:'OpenAlex citation metadata + Crossref update notices',
   cta:'Trace evidence',run:()=>load(),has:()=>!!data,seed:()=>load(true)},
 design:{panel:'designpanel',line:'lineDesign',label:'DESIGN A TRIAL AGAINST THE REGISTRY, NOT JUST THE LITERATURE',
   hint:'Registered trials with posted results, matched to the published record',
   has:()=>!!design,seed:()=>{listCohorts();runDesign()}},
 reviewer:{panel:'reviewerpanel',line:'lineReviewer',label:'CHECK A CANDIDATE REVIEWER AGAINST THE MANUSCRIPT AUTHORS',
   hint:'Coauthorship paths from the OpenAlex author graph, with the shared works behind each step',
   has:()=>!!reviewer,seed:()=>runReviewer()},
 trial:{panel:'trialpanel',line:'lineTrial',label:'COMPARE WHAT WAS REGISTERED WITH WHAT WAS PUBLISHED',
   hint:'ClinicalTrials.gov registration matched to its publications through PubMed',
   cta:'Compare',has:()=>!!trial,seed:()=>runTrial()},
 search:{panel:'searchpanel',line:'lineSearch',label:'SEARCH EVERY INDEXED TRIAL AND PAPER',
   hint:'Keyword retrieval over the Elasticsearch index that feeds fuzzy matching',
   has:()=>!!searchResult,seed:()=>runSearch()},
};
const PANELS=['sourcepanel','workspace','designpanel','reviewerpanel','trialpanel','searchpanel'];
const LINES=['lineDoi','lineDesign','lineReviewer','lineTrial','lineSearch'];

function setMode(next){mode=next;const m=MODES[next];
 for(const k in MODES)$('#mode'+k).classList.toggle('active',k===next);
 PANELS.forEach(id=>$('#'+id).hidden=(id!==m.panel));
 LINES.forEach(id=>$('#'+id).hidden=(id!==m.line));
 $('#depth').hidden=next!=='trace';$('#breadth').hidden=next!=='trace';
 $('#searchlabel').textContent=m.label;$('#searchsources').textContent=m.hint;
 if(m.cta&&next!=='trial')$('#explore').innerHTML=m.cta+' <span>↗</span>';
 $('#demo').hidden=!(next==='sources'||next==='trace');
 message('');
 // Each mode loads its own data once, from a saved snapshot where one exists,
 // so switching tabs never waits on a live lookup.
 if(!m.has())m.seed()}
Object.keys(MODES).forEach(k=>$('#mode'+k).onclick=()=>setMode(k));
$('#search').onsubmit=e=>{e.preventDefault();const r=MODES[mode].run;r?r():MODES[mode].seed()};
$('#rundesign').onclick=e=>{e.preventDefault();runDesign()};
$('#runreviewer').onclick=e=>{e.preventDefault();runReviewer()};
$('#runtrial').onclick=e=>{e.preventDefault();runTrial()};
$('#runsearch').onclick=e=>{e.preventDefault();runSearch()};$('#demo').onclick=()=>setMode('sources');$('#filter').onchange=draw;$('#find').oninput=draw;
async function checkSources(demo=false){if(busy)return;busy=true;$('#explore').disabled=true;$('#demo').disabled=true;
message(demo?'Loading the saved reference check…':'Reading the reference list and checking each work for retraction notices…');
try{const r=await fetch(demo?'/api/demo-sources':'/api/sources?'+new URLSearchParams({doi:$('#doi').value}));const result=await r.json();
if(!r.ok)throw Error(result.error);sources=result;if(result.paper&&result.paper.doi)$('#doi').value=result.paper.doi;renderSources();message(result.warnings.join(' '),false)}
catch(e){message(e.message||'Could not read this reference list. Try the saved example.',true)}
finally{busy=false;$('#explore').disabled=false;$('#demo').disabled=false}}

function renderSources(){const s=sources,p=s.paper,hit=s.retracted_references,soft=s.updated_references;
const tone=hit?'bad':soft?'warn':'ok';
const verdict=hit?`${hit} of this paper's ${s.references_screened} checked references ${hit===1?'has':'have'} been retracted`
 :soft?`No retractions found, but ${soft} reference${soft===1?' carries':'s carry'} another update notice`
 :`No retraction notices found among ${s.references_screened} checked references`;
$('#sourcepanel').innerHTML=`<div class="sectionhead"><div><span class="eyebrow">REFERENCE INTEGRITY CHECK</span><h2>${esc(p.title)}</h2></div><div class="sourcepill">${s.mode==='snapshot'?'● Saved real-data example · ':'● Live check · '}${esc(p.journal)} · ${p.year||'year unavailable'}</div></div>
${p.is_retracted?'<div class="verdict bad"><b>This paper itself carries a retraction notice.</b></div>':''}
<div class="verdict ${tone}"><b>${esc(verdict)}</b><span>${p.citations.toLocaleString()} citations · ${s.references_total} references listed · ${s.references_screened} resolved and screened</span></div>
${s.flagged.length?`<div class="flaglist">${s.flagged.map(f=>{const r=f.retraction;return `<article class="flagcard ${r.status==='retracted'?'bad':'warn'}">
<div class="flaghead"><span class="badge ${r.status==='retracted'?'':'neutral'}">${esc(statuses[r.status]||r.status)}</span><span class="small">${f.year||'—'} · ${f.citations.toLocaleString()} citations</span></div>
<h4>${esc(f.title)}</h4>
${r.notices&&r.notices.length?r.notices.map(v=>`<div class="evidencebox"><a href="${esc(doiLink(v.doi))}" target="_blank" rel="noreferrer">${esc(v.title)} ↗</a><p>${esc(v.type)} · ${v.date?esc(v.date.slice(0,10)):'date unavailable'} · ${esc(v.source)}</p></div>`).join(''):`<p class="small">${esc(r.reason||'No notice detail returned by Crossref.')}</p>`}
<div class="flagactions">${f.doi?`<a class="external" href="${esc(doiLink(f.doi))}" target="_blank" rel="noreferrer">Open the cited paper ↗</a>`:''}<button class="external" data-trace="${esc(f.doi||'')}">See how far this spread →</button></div>
</article>`}).join('')}</div>`
 :'<p class="empty">Nothing was flagged. Read the coverage note below before treating that as a clean bill of health.</p>'}
<details class="methods" open><summary>What was and was not checked</summary><p>${esc(s.method)}</p><p>${esc(s.interpretation)}</p>${s.warnings.length?`<p>${esc(s.warnings.join(' '))}</p>`:''}</details>`;
document.querySelectorAll('[data-trace]').forEach(el=>el.onclick=()=>{if(!el.dataset.trace)return;$('#doi').value=el.dataset.trace;setMode('trace');load()})}

function setView(v){view=v;$('#graphwrap').hidden=v!=='graph';$('#paperlist').hidden=v!=='list';$('#graphview').classList.toggle('active',v==='graph');$('#listview').classList.toggle('active',v==='list')}
$('#graphview').onclick=()=>setView('graph');$('#listview').onclick=()=>setView('list');$('#zoomin').onclick=()=>{zoom=Math.min(2.5,zoom+.2);draw()};$('#zoomout').onclick=()=>{zoom=Math.max(.5,zoom-.2);draw()};$('#reset').onclick=()=>{zoom=1;offset={x:0,y:0};draw()};
let drag;$('#graph').onpointermove=e=>{if(!drag)return;const rect=$('#graph').getBoundingClientRect();offset={x:(e.clientX-drag.x)*900/rect.width+drag.ox,y:(e.clientY-drag.y)*570/rect.height+drag.oy};draw()};$('#graph').onpointerdown=e=>{if(e.target.closest('.node'))return;drag={x:e.clientX,y:e.clientY,ox:offset.x,oy:offset.y};$('#graph').setPointerCapture(e.pointerId)};$('#graph').onpointerup=()=>drag=null;$('#graph').onpointercancel=()=>drag=null;
$('#method').onclick=()=>{$('#methodology').open=true;$('#methodology').scrollIntoView({behavior:'smooth'})};$('#export').onclick=()=>{if(!data)return;const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='evidence-atlas.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
let step=0;const steps=[
 ['Start with a paper you rely on','This is a real Nature Reviews Clinical Oncology review. We read all 182 works it cites and checked every one for a retraction notice.'],
 ['One of its sources was retracted','The flagged reference was retracted in April 2023, confirmed by both Retraction Watch and the publisher. The notice is linked, so you can verify it yourself.'],
 ['Now ask how far that spread','Switching to the citation view, centred on the retracted paper. Red is the retracted work, orange cites it directly, yellow connects through another paper.'],
 ['Timing is the part people miss','Most of the papers connected to this retraction were published after the notice appeared. That is a fact about dates, not an accusation about the authors.'],
 ['Keep pulling the thread','Select any paper to see its shortest path back to the retraction, make it the new starting point, or check its own reference list. Saved mode works with no network at all.'],
];
async function showStep(){$('#stepnumber').textContent='GUIDED DEMO · '+(step+1)+' / '+steps.length;
 $('#steptitle').textContent=steps[step][0];$('#steptext').textContent=steps[step][1];
 $('#nextstep').textContent=step===steps.length-1?'Explore it yourself':'Next →';
 if(step<=1){if(mode!=='sources')setMode('sources');if(!sources)await checkSources(true)}
 else{if(mode!=='trace'){mode='trace';setMode('trace')}if(!data||data.mode!=='snapshot')await load(true);
  if(data)select(step===4?(data.nodes.find(n=>n.exposure==='indirect')||data.nodes[0]).id:data.seed)}}
$('#tour').onclick=async()=>{step=0;$('#filter').value='all';$('#find').value='';setView('graph');await showStep();$('#tourdialog').showModal()};
$('#closetour').onclick=()=>$('#tourdialog').close();
$('#nextstep').onclick=async()=>{if(step===steps.length-1){$('#tourdialog').close();return}step++;await showStep()};
setMode('sources');
