"""Extracted verbatim from bluetools.py (see blue/server/pages).

Do not import bluetools here; this module is pure data.
"""

DUET_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blue &amp; Hexia — Let them talk</title>
<link rel="stylesheet" href="/assets/blue.css">
<script src="/assets/blue.js" defer></script>
<style>
 :root{ --bluec:#3da9fc; --hexiac:#b06cf0;
   --cream:#faf8f4; --paper:#ffffff; --ink:#1a2e1a; --forest:#4a6b4a;
   --sage:#8fae8f; --slate:#64748b; --blue:#3b82f6; --gold:#d4af37;
   --line:#cfc9bd; --shadow:0 1px 3px rgba(0,0,0,.06); }
 body{font-family:-apple-system,'Segoe UI',sans-serif;background:var(--cream);color:var(--ink);max-width:760px;margin:0 auto;padding:26px 18px;line-height:1.5}
 h1{font-size:1.5em;margin-bottom:4px}
 p.sub{color:var(--slate);margin-bottom:16px;font-size:.95em}
 .controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
 input[type=text]{flex:1;min-width:200px;padding:10px 12px;border:1px solid var(--line);border-radius:8px;font:inherit}
 select,button{padding:9px 13px;border:1px solid var(--line);border-radius:8px;background:var(--paper);font:inherit;cursor:pointer;color:var(--ink)}
 button.primary{background:#1a2e1a;color:#fff;border-color:#1a2e1a}
 button:disabled{opacity:.5;cursor:default}
 .muted{color:var(--slate);font-size:.9em}
 #log{display:flex;flex-direction:column;gap:10px;margin-top:12px}
 .turn{padding:10px 14px;border-radius:14px;max-width:84%;box-shadow:var(--shadow)}
 .turn .who{font-size:.7em;text-transform:uppercase;letter-spacing:.08em;font-weight:700;margin-bottom:3px}
 .turn.blue{align-self:flex-start;background:#eaf4ff;border:1px solid #cfe4fb}
 .turn.blue .who{color:var(--bluec)}
 .turn.hexia{align-self:flex-end;background:#f4ecfc;border:1px solid #e6d6f7}
 .turn.hexia .who{color:var(--hexiac)}
 .turn.speaking{box-shadow:0 0 0 2px currentColor}
 .qpanel{border:1px solid var(--line);border-radius:10px;padding:12px;background:var(--paper);margin:8px 0 14px;box-shadow:var(--shadow)}
 .qhead{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px}
 .qmode{display:flex;gap:6px;flex-wrap:wrap}
 .qmode button.active{background:#1a2e1a;color:#fff;border-color:#1a2e1a}
 #questionText{width:100%;min-height:74px;box-sizing:border-box;border:1px solid var(--line);border-radius:8px;padding:10px 12px;font:inherit;resize:vertical;color:var(--ink);background:var(--paper)}
 .qactions{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:9px}
 #qRecordBtn.recording{background:#e9534e;border-color:#e9534e;color:#fff}
 .srcbox{border:1px solid var(--line);border-radius:8px;padding:8px;max-height:180px;overflow:auto;background:var(--paper);font-size:.9em}
 .srcbox .fold{font-size:.72em;text-transform:uppercase;letter-spacing:.06em;color:var(--forest);margin:7px 0 3px;font-weight:600}
 .srcbox .fold:first-child{margin-top:0}
 .srcbox label{display:flex;gap:7px;align-items:flex-start;padding:3px 0;cursor:pointer}
 .srcbox input{margin-top:3px;flex:none}
 .srccount{font-size:.8em;color:var(--slate)}
 /* 🔬 deep dive: the live shared notebook — the theory under construction. */
 #notebookPanel{border:1px dashed var(--line);border-radius:10px;padding:8px 12px;background:var(--paper);margin-top:12px}
 #notebookPanel summary{cursor:pointer;font-weight:600;color:var(--forest);font-size:.9em}
 #notebookPanel .nbrow{margin:4px 0;font-size:.88em;color:var(--ink);line-height:1.45}
 #notebookPanel .nbrow b{color:var(--forest);font-size:.82em;text-transform:uppercase;letter-spacing:.05em}
 #notebookPanel .nbstamp{font-size:.75em;color:var(--slate);margin-top:6px}
 #notebookPanel .workspace{display:grid;grid-template-columns:minmax(112px,150px) 1fr;gap:5px 10px;border-bottom:1px solid var(--line);padding:8px 0 10px;margin-bottom:8px}
 #notebookPanel .wlabel{font-size:.72em;text-transform:uppercase;letter-spacing:.06em;color:var(--forest);font-weight:700}
 #notebookPanel .wvalue{font-size:.88em;color:var(--ink);line-height:1.35;min-width:0;overflow-wrap:anywhere}
 #notebookPanel .wempty{color:var(--slate);font-style:italic}
 #notebookPanel .statusMatrix{grid-column:1/-1;display:grid;grid-template-columns:repeat(4,minmax(90px,1fr));gap:6px;margin-bottom:4px}
 #notebookPanel .statusCell{border:1px solid var(--line);border-radius:8px;background:#fff;padding:6px 7px;min-width:0}
 #notebookPanel .statusCell b{display:block;font-size:.68em;text-transform:uppercase;letter-spacing:.06em;color:var(--forest);margin-bottom:2px}
 #notebookPanel .statusCell span{display:block;font-size:.82em;color:var(--ink);overflow-wrap:anywhere}
 #notebookPanel .liveArtifact{grid-column:1/-1;border-top:1px solid var(--line);padding-top:8px;margin-top:4px}
 #notebookPanel .artifactTitle{font-size:.74em;text-transform:uppercase;letter-spacing:.06em;color:var(--forest);font-weight:700;margin-bottom:5px}
 #notebookPanel .artifactHint{font-size:.76em;color:var(--slate);margin-bottom:6px}
 #notebookPanel .artifactTable{width:100%;border-collapse:collapse;table-layout:fixed;font-size:.82em;background:#fff}
 #notebookPanel .artifactTable th,#notebookPanel .artifactTable td{border:1px solid var(--line);padding:6px 7px;vertical-align:top;overflow-wrap:anywhere}
 #notebookPanel .artifactTable th{background:#f3f7f1;color:var(--forest);text-align:left;font-weight:700}
 #notebookPanel .artifactTable td:first-child{font-weight:600;background:#fafbf8;width:24%}
 #notebookPanel .artifactTable td[contenteditable="true"]{min-height:28px;outline:none}
 #notebookPanel .artifactTable td[contenteditable="true"]:focus{box-shadow:inset 0 0 0 2px var(--forest);background:#fffef6}
 #notebookPanel .rawNotebook{border-top:1px solid var(--line);padding-top:6px}
 #notebookPanel .rawNotebook summary{font-size:.78em;color:var(--slate);font-weight:600}
 #conceptGraph{display:none;margin-top:10px;border-top:1px solid var(--line);padding-top:8px}
 #conceptGraph .gtitle{font-size:.72em;text-transform:uppercase;letter-spacing:.06em;color:var(--forest);font-weight:700;margin-bottom:6px}
 #conceptGraph .gbody{display:flex;gap:8px;align-items:stretch;overflow:auto;padding-bottom:2px}
 #conceptGraph .gnode{min-width:112px;max-width:170px;border:1px solid var(--line);border-radius:8px;background:#fff;padding:6px 8px;font-size:.78em;line-height:1.25;box-shadow:var(--shadow)}
 #conceptGraph .gnode.core{border-color:var(--forest);background:#f3f7f1;font-weight:600}
 #conceptGraph .gnode.supported{border-color:#74a66a}
 #conceptGraph .gnode.tentative{border-color:#d4af37}
 #conceptGraph .gnode.contested{border-color:#d46a6a}
 #conceptGraph .gedge{align-self:center;color:var(--slate);font-size:.85em}
 #conceptGraph .gedge.supported{color:#3f8f4a}
 #conceptGraph .gedge.tentative{color:#b58a13}
 #conceptGraph .gedge.contested{color:#c54a4a}
 /* Midnight: the robots' identity bubbles become glass tints. */
 :root:not([data-theme="light"]) .turn.blue{background:rgba(61,169,252,.12);border-color:rgba(61,169,252,.35)}
 :root:not([data-theme="light"]) .turn.hexia{background:rgba(176,108,240,.12);border-color:rgba(176,108,240,.35)}
</style></head><body>
<h1>Blue &amp; Hexia</h1>
<p class="sub">Give them a topic or a link to discuss, or assign each one a role or perspective to argue &mdash; then watch them go. Checked readings become that robot's source boundary for the duet. Each speaks in their own voice and moves their own head, taking turns. (Both heads connected works best; if a head is off it just won't move.)</p>
<p class="sub" id="devNote" style="margin-top:-8px;display:none"></p>
<div class="controls">
 <input type="text" id="topic" placeholder="Topic (optional) — e.g. what makes a good story">
</div>
<div class="controls">
 <input type="text" id="url" placeholder="Link (optional) — paste an article or YouTube URL for them to discuss">
</div>
<div class="controls">
 <input type="text" id="roleBlue" placeholder="Blue's role / perspective (optional) — e.g. argue cities beat small towns">
 <input type="text" id="roleHexia" placeholder="Hexia's role / perspective (optional) — e.g. a sceptical detective">
</div>
<div class="controls">
 <input type="text" id="toneBlue" placeholder="Blue's tone (optional) — e.g. dry and sardonic">
 <input type="text" id="toneHexia" placeholder="Hexia's tone (optional) — e.g. bubbly and dramatic">
</div>
<div class="controls">
 <input type="text" id="slangBlue" placeholder="Blue's slang / dialect (optional) — e.g. 1920s slang">
 <input type="text" id="slangHexia" placeholder="Hexia's slang / dialect (optional) — e.g. Gen Z slang">
</div>
<div class="controls">
 <label class="muted" style="flex:1;display:flex;flex-direction:column;gap:4px">Blue's voice<select id="voiceBlue"></select></label>
 <label class="muted" style="flex:1;display:flex;flex-direction:column;gap:4px">Hexia's voice<select id="voiceHexia"></select></label>
</div>
<div class="controls">
 <label class="muted" style="flex:1;display:flex;flex-direction:column;gap:4px">Blue's speed<select id="rateBlue"><option value="auto">Default</option><option value="0.7">Slower</option><option value="0.85">Slow</option><option value="1.0">Normal</option><option value="1.15">Brisk</option><option value="1.3">Fast</option></select></label>
 <label class="muted" style="flex:1;display:flex;flex-direction:column;gap:4px">Hexia's speed<select id="rateHexia"><option value="auto">Default</option><option value="0.7">Slower</option><option value="0.85">Slow</option><option value="1.0">Normal</option><option value="1.15">Brisk</option><option value="1.3">Fast</option></select></label>
</div>
<div class="controls">
 <div style="flex:1;display:flex;flex-direction:column;gap:5px">
  <span class="muted">Blue checked readings — only these library docs (<span class="srccount" id="cntBlue">0</span> selected)</span>
  <div id="sourcesBlue" class="srcbox" style="border-color:#cfe4fb"></div>
 </div>
 <div style="flex:1;display:flex;flex-direction:column;gap:5px">
  <span class="muted">Hexia checked readings — only these library docs (<span class="srccount" id="cntHexia">0</span> selected)</span>
  <div id="sourcesHexia" class="srcbox" style="border-color:#e6d6f7"></div>
 </div>
</div>
<div class="controls">
 <label class="muted" title="How spirited the discussion is — calm and agreeable at the left, provocative and sparring at the right" style="flex:1;display:flex;align-items:center;gap:10px;min-width:240px">Spice
  <input type="range" id="spice" min="0" max="10" step="1" value="5" style="flex:1">
  <span id="spiceVal" class="muted" style="min-width:96px;text-align:right">balanced</span></label>
</div>
<div class="controls">
 <select id="turns"><option value="4">4 turns</option><option value="6" selected>6 turns</option><option value="8">8 turns</option><option value="10">10 turns</option><option value="20">20 turns</option><option value="0">until I stop</option></select>
 <select id="starter"><option value="hexia">Hexia starts</option><option value="blue">Blue starts</option></select>
 <button class="primary" id="startBtn">Start</button>
 <button id="questionBtn" disabled title="Pause the duet so a student can ask a question">Question</button>
 <button id="pauseBtn" disabled title="Pause after the current spoken line, then continue without restarting">Pause</button>
 <button id="stopBtn" disabled>Stop</button>
 <button id="saveBtn" disabled title="Download the written dialogue (with the run's settings) as a Markdown file">💾 Save</button>
 <label class="muted"><input type="checkbox" id="speakChk" checked> speak aloud</label>
 <label class="muted" title="They search the internet for the subject first and ground the conversation in what they find"><input type="checkbox" id="researchChk"> research the web</label>
 <label class="muted" title="While they talk, Blue watches his inbox: an email with duet in the subject joins the conversation live, and the sender gets their spoken answer mailed back"><input type="checkbox" id="mailChk" checked> 📧 answer duet mail</label>
 <label class="muted" title="They know students are listening: jargon gets glossed in a breath, examples land in student life, they sometimes address the room, and the final turns end on a position plus a question for the class"><input type="checkbox" id="classChk"> 🎓 classroom mode</label>
 <label class="muted" title="They read the best-matching Wikipedia article on the subject first and ground the conversation in it"><input type="checkbox" id="wikiChk"> consult Wikipedia</label>
 <label class="muted" title="Keep Alex's private family and household details out of the robots' dialogue"><input type="checkbox" id="noFamilyChk" checked> no family refs</label>
 <label class="muted" title="Joint research protocol: Builder and Examiner jobs, phases, and a canonical notebook of competing models, blocking active tasks, first-class experiments, execution modes, evidence-gated edits, validation decisions, confidence provenance, dependencies, archives, reopenings and concept compression — so the talk carries inquiry cycles to completion"><input type="checkbox" id="protoChk"> 🔬 deep dive</label>
</div>
<div id="questionPanel" class="qpanel" style="display:none">
 <div class="qhead">
  <b>Student question</b>
  <div class="qmode">
   <button id="qTypeBtn" class="active" type="button">Type</button>
   <button id="qSpeakBtn" type="button">Speak</button>
  </div>
 </div>
 <textarea id="questionText" placeholder="Type the student's question here"></textarea>
 <div id="qSpeakBox" style="display:none">
  <button id="qRecordBtn" type="button">Start recording</button>
  <span id="qRecordStatus" class="muted">Speak the question, then stop recording.</span>
 </div>
 <div class="qactions">
  <button class="primary" id="qSubmitBtn" type="button">Send question</button>
  <button id="qCancelBtn" type="button">Cancel</button>
  <span class="muted" id="qStatus">Dialogue paused while the question is open.</span>
 </div>
</div>
<div id="usbHeads" class="controls" style="display:none;flex-direction:column;align-items:stretch;gap:10px;border:1px dashed #cfc9bd;border-radius:10px;padding:12px;background:#fff">
 <div class="muted" style="font-weight:600;color:#1a2e1a">Heads on this device (USB-C)</div>
 <div style="display:flex;gap:10px;flex-wrap:wrap">
  <div style="flex:1;min-width:210px;display:flex;flex-direction:column;gap:6px;border:1px solid #cfe4fb;border-radius:8px;padding:8px">
   <div><b style="color:var(--bluec)">Blue</b> &mdash; <span id="stBlueHead" class="muted">not connected</span></div>
   <div style="display:flex;gap:6px;flex-wrap:wrap">
    <button id="connBlue">Connect</button><button id="nodBlue" disabled>Nod (test)</button><button id="discBlue" disabled>Disconnect</button>
   </div>
  </div>
  <div style="flex:1;min-width:210px;display:flex;flex-direction:column;gap:6px;border:1px solid #e6d6f7;border-radius:8px;padding:8px">
   <div><b style="color:var(--hexiac)">Hexia</b> &mdash; <span id="stHexiaHead" class="muted">not connected</span></div>
   <div style="display:flex;gap:6px;flex-wrap:wrap">
    <button id="connHexia">Connect</button><button id="nodHexia" disabled>Nod (test)</button><button id="discHexia" disabled>Disconnect</button>
   </div>
  </div>
 </div>
 <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
  <button id="swapHeads">Swap Blue/Hexia</button>
  <span class="muted" style="font-size:.85em">Plug Blue and Hexia into this Mac, Connect each, then Nod to check which is which (Swap if needed).</span>
 </div>
</div>
<details id="notebookPanel" style="display:none" open>
 <summary>📓 Shared research notebook — the knowledge base they're testing</summary>
 <div id="notebookBody"></div>
 <div id="conceptGraph"></div>
 <div class="nbstamp" id="notebookStamp"></div>
</details>
<div id="log"></div>
<script src="/js/ohbot-heads.js"></script>
<script>
const ROBOTS = {{ robots_json|safe }};
const DOCS = {{ documents_json|safe }};

// blueDeviceTag / DRIVES_HEADS / WEBSERIAL_OK / LOCAL_DRIVERS and the whole
// OhbotSerialDriver + connect helpers come from /js/ohbot-heads.js (loaded
// above), shared with the chat and calibration pages.
(function(){
  var byF={}; DOCS.forEach(function(d){ var f=d.folder||'(root)'; (byF[f]=byF[f]||[]).push(d.filename); });
  var counts={sourcesBlue:'cntBlue', sourcesHexia:'cntHexia'};
  ['sourcesBlue','sourcesHexia'].forEach(function(id){
    var box=document.getElementById(id); if(!box) return;
    Object.keys(byF).forEach(function(f){
      var h=document.createElement('div'); h.className='fold'; h.textContent=f; box.appendChild(h);
      byF[f].forEach(function(fn){
        var lab=document.createElement('label');
        var cb=document.createElement('input'); cb.type='checkbox'; cb.value=fn;
        var sp=document.createElement('span'); sp.textContent=fn;
        lab.appendChild(cb); lab.appendChild(sp); box.appendChild(lab);
      });
    });
    box.addEventListener('change', function(){
      var n=box.querySelectorAll('input:checked').length;
      var c=document.getElementById(counts[id]); if(c) c.textContent=n;
    });
  });
})();
function selVals(id){ var box=document.getElementById(id); if(!box) return [];
  return Array.prototype.slice.call(box.querySelectorAll('input:checked')).map(function(c){return c.value;}); }
function SOURCES(){ return { blue: selVals('sourcesBlue'), hexia: selVals('sourcesHexia') }; }
function fieldMap(prefix){ var g=function(id){var e=document.getElementById(id);return e?(e.value||'').trim():'';}; return { blue:g(prefix+'Blue'), hexia:g(prefix+'Hexia') }; }
function SPICE(){ var s=document.getElementById('spice'); var n=s?parseInt(s.value,10):5; return isNaN(n)?5:n; }
(function(){ var s=document.getElementById('spice'), v=document.getElementById('spiceVal'); if(!s||!v) return;
  var word=function(n){ n=+n; return n<=1?'easygoing':n<=3?'gentle':n<=4?'mellow':n===5?'balanced':n<=7?'lively':n<=8?'spirited':'provocative'; };
  var upd=function(){ v.textContent=word(s.value); }; s.addEventListener('input',upd); upd();
})();
// ---- Settings persistence: everything typed or ticked survives a reload ----
// Saved to localStorage on every change; restored on load. (Voices and speeds
// already persist separately via blueVoiceName_/blueVoiceRate_.)
const SETTINGS_KEY='duetSettings.v1';
const SET_TXT=['topic','url','roleBlue','roleHexia','toneBlue','toneHexia','slangBlue','slangHexia'];
const SET_SEL=['turns','starter'];
const SET_CHK=['speakChk','researchChk','mailChk','classChk','wikiChk','noFamilyChk','protoChk'];
function saveSettings(){
  try{
    const s={txt:{},sel:{},chk:{},spice:SPICE(),src:SOURCES()};
    SET_TXT.forEach(function(id){ const e=document.getElementById(id); if(e) s.txt[id]=e.value; });
    SET_SEL.forEach(function(id){ const e=document.getElementById(id); if(e) s.sel[id]=e.value; });
    SET_CHK.forEach(function(id){ const e=document.getElementById(id); if(e) s.chk[id]=e.checked; });
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
  }catch(e){}
}
function restoreSettings(){
  let s=null; try{ s=JSON.parse(localStorage.getItem(SETTINGS_KEY)||'null'); }catch(e){}
  if(!s) return;
  try{
    SET_TXT.forEach(function(id){ const e=document.getElementById(id); if(e && typeof (s.txt||{})[id]==='string') e.value=s.txt[id]; });
    SET_SEL.forEach(function(id){ const e=document.getElementById(id); if(e && (s.sel||{})[id]!=null) e.value=s.sel[id]; });
    SET_CHK.forEach(function(id){ const e=document.getElementById(id); if(e && typeof (s.chk||{})[id]==='boolean') e.checked=s.chk[id]; });
    const sp=document.getElementById('spice');
    if(sp && s.spice!=null){ sp.value=s.spice; sp.dispatchEvent(new Event('input')); }
    ['sourcesBlue','sourcesHexia'].forEach(function(id){
      const want=((s.src||{})[id==='sourcesBlue'?'blue':'hexia'])||[];
      const box=document.getElementById(id); if(!box) return;
      Array.prototype.slice.call(box.querySelectorAll('input[type=checkbox]')).forEach(function(cb){
        cb.checked = want.indexOf(cb.value)>=0;
      });
      box.dispatchEvent(new Event('change'));   // refresh the "n selected" badge
    });
  }catch(e){}
}
(function(){
  SET_TXT.concat(SET_SEL,SET_CHK,['spice']).forEach(function(id){
    const e=document.getElementById(id); if(!e) return;
    e.addEventListener('change', saveSettings); e.addEventListener('input', saveSettings);
  });
  ['sourcesBlue','sourcesHexia'].forEach(function(id){ const e=document.getElementById(id); if(e) e.addEventListener('change', saveSettings); });
  restoreSettings();
})();
let running=false, history=[], DIRECTION='';   // DIRECTION = the conversation's evolving bearing (see maybeReflect); in 🔬 deep-dive mode it's the shared notebook
let LAST_PHASE='', LAST_BUILDER='';            // 🔬 deep-dive protocol: for surfacing phase changes and job swaps as notes
let STALL=0;                                   // consecutive reflects where the notebook barely changed (server-diffed)
let MOVETYPES=[];                              // keeper-reported MOVED labels, most recent last (movement-monotony watch)
let ARCS=[];                                   // keeper-INFERRED inquiry stages (arc-stuck watch)
let NBQ=[], LAST_OBS='';                       // queued notebook observations (the notebook's own voice)
let REFLECTS=0;                                // protocol notebook refreshes; periodic progress + paradigm checks
let OPFAILS=0;                                 // consecutive requested operations the keeper marked MISSED
let GATEFAILS=0;                               // consecutive notebook edits rejected by evidence/validation gate
let PROMOTIONFAILS=0;                          // consecutive over-promotion attempts rejected by promotion gate
let ACTIVE_TASK='';                            // blocking notebook workflow item, e.g. E1 EXECUTING
let ACTIVE_TASK_ATTEMPTS=0;                    // repeated reflects on the same blocking task
let ARTIFACT_PLAN='';                          // construction-order note from ARTIFACT PLANNER / TASK REVISION
let ARTIFACT_MODE='';                          // lock into direct artifact manipulation, e.g. OS1/E1 table fill
let ARTIFACT_SILENCE=0;                        // turns where notebook observations stay silent after a lock
let ART_REQ=0, ART_CREATED=0, ART_POPULATED=0, ART_USED=0; // coarse artifact completion metrics
let KERNELFAILS=0;                             // consecutive kernel request denials
let PROTOCOL_AUDIT='';                         // compressed violation summary from the notebook
let KERNEL_HEALTH='NORMAL';                    // NORMAL/WARNING/RECOVERING/PAUSED; workflow deadlock is separate
let WORKFLOW_STATE='IDLE';                     // IDLE/BLOCKED/EXECUTING/DEADLOCKED; separate from kernel health
let DEADLOCKED=false;                          // workflow deadlock detected by notebook/browser
let LAST_RECOVERY_TURN=0;                      // last turn where a blocked workflow recovered
function PROTO(){ const c=document.getElementById('protoChk'); return !!(c && c.checked); }
// Movement monotony: the same MOVED type three reflects running (e.g. nothing but
// additions) => oneTurn sends it and the server forces the complementary move.
function MONO(){ const n=MOVETYPES.length; if(n<3) return '';
  const t=MOVETYPES[n-1]; return (MOVETYPES[n-2]===t && MOVETYPES[n-3]===t)?t:''; }
// Arc stuck: the keeper inferred the SAME inquiry stage three reflects running
// ("20 turns challenging, nothing repaired") => force the stage-advancing move.
function ARCSTUCK(){ const n=ARCS.length; if(n<3) return '';
  const t=ARCS[n-1]; return (ARCS[n-2]===t && ARCS[n-3]===t)?t:''; }
function updateKernelDeadlock(){
  if(!PROTO()) return false;
  const blockedLongEnough=ACTIVE_TASK && ACTIVE_TASK_ATTEMPTS>=6;
  const repeatedFailure=(KERNELFAILS>0 || OPFAILS>0 || GATEFAILS>0 || PROMOTIONFAILS>0);
  const noMovement=STALL>=2;
  if(blockedLongEnough && repeatedFailure && noMovement){
    DEADLOCKED=true; WORKFLOW_STATE='DEADLOCKED';
    const msg='DEADLOCK DETECTED: '+ACTIVE_TASK+' has repeated the same blocked transition '+ACTIVE_TASK_ATTEMPTS+' times with no notebook movement. Last successful recovery turn '+(LAST_RECOVERY_TURN||'none')+'. Set aside the blocked object, identify its unmet dependency, resume the prerequisite, and name the next resolvable operation without narrating kernel state.';
    if(NBQ.indexOf(msg)<0) NBQ.push(msg);
    return true;
  }
  if(!repeatedFailure && DEADLOCKED){
    DEADLOCKED=false; WORKFLOW_STATE='RECOVERING'; KERNEL_HEALTH='RECOVERING'; LAST_RECOVERY_TURN=history.length;
  }
  return false;
}
function nbSections(txt){
  const out={};
  (txt||'').split('\\n').forEach(function(x){
    const m=/^([A-Z][A-Z_ ]{2,}):\\s*(.*)$/.exec((x||'').trim());
    if(m) out[m[1].replace(/_/g,' ')]=m[2]||'';
  });
  return out;
}
function graphStatus(text){
  text=(text||'').toLowerCase();
  if(/\\b(refuted|rejected|denied|abandoned|failed|contested|contradiction|missed|needs_reevaluation|needs re-evaluation)\\b/.test(text)) return 'contested';
  if(/\\b(supported|accepted|confirmed|completed|survived)\\b/.test(text)) return 'supported';
  return 'tentative';
}
function graphLabel(text, fallback){
  text=(text||'').replace(/[<>{}\\[\\]]/g,' ').replace(/\\s+/g,' ').trim();
  if(!text || text==='-' || text==='—') return fallback;
  const id=/\\b((?:CG|PM|CD|CU|DR|VL|BC|FM|DP|CE|MEC|MC|MS|CC|EP|OS|KG|[ACDEHIMOPRSTV])\\d+)\\b/.exec(text);
  const before=(id?text.slice(0, text.indexOf(id[1])):text).split(/[;,.]/)[0].trim();
  const label=(id?id[1]+' ':'')+(before||text.split(/[;,.]/)[0]||fallback);
  return label.slice(0,72);
}
function renderConceptGraph(){
  const g=document.getElementById('conceptGraph'); if(!g) return;
  if(!PROTO() || !DIRECTION){ g.style.display='none'; g.innerHTML=''; return; }
  const s=nbSections(DIRECTION), nodes=[];
  const add=function(label, cls){ if(label && nodes.map(function(n){return n.label;}).indexOf(label)<0) nodes.push({label:label, cls:cls||'tentative'}); };
  add(graphLabel(s.FOCUS||s.CENTRAL,'Discrimination target'), 'core');
  ['KERNEL DECISION','KERNEL HEALTH','KERNEL REVIEW','INQUIRY PAUSE','PROTOCOL AUDIT','DEPENDENCY SOLVER','ARTIFACT PLANNER','ARTIFACT COMPILER','TASK REVISION','ARTIFACT MODE','ARTIFACT EDITOR','ACTIVE TASK','WORK QUEUE','RECOVERY STRATEGY','INQUIRY PATTERNS','CONCEPT REGISTER','DESIGN VARIABLES','OPERATIONAL CRITERIA','DEFINITION CONFLICTS','DEFINITION REVISION','MECHANISMS','MECHANISM SPLIT','MECHANISM CANDIDATES','CAUSAL GRAPH','CAUSAL CLAIMS','INTERPRETATIONS','ALTERNATIVE INTERPRETATIONS','EXPLANATORY PATHS','REPLICATIONS','PROMOTION GATE','KNOWLEDGE GRAPH','COUNTEREXAMPLES','THEORY HEALTH','DISAGREEMENTS','EVENT SEVERITY','REVISION IMPACT','EXPERIMENTS','OBSERVATIONS','OBSERVATION SETS','SALVAGE','COMPETING MODELS','SUPPORTED','EVIDENCE','WORKING DEFINITIONS','HYPOTHESES','MODEL OBJECTS','ARTIFACTS','DISCRIMINATORS','DEPENDENCIES','STATUS LEDGER','CHANGE LOG','INQUIRY CYCLES','ARTIFACT METRICS','REGISTERS'].forEach(function(k){
    (s[k]||'').split(';').slice(0,3).forEach(function(part){ add(graphLabel(part,''), graphStatus(part)); });
  });
  if(nodes.length<2){ g.style.display='none'; g.innerHTML=''; return; }
  g.style.display='block'; g.innerHTML='';
  const title=document.createElement('div'); title.className='gtitle'; title.textContent='Concept graph'; g.appendChild(title);
  const body=document.createElement('div'); body.className='gbody'; g.appendChild(body);
  nodes.slice(0,8).forEach(function(n,i){
    if(i>0){ const e=document.createElement('div'); e.className='gedge '+(n.cls||'tentative'); e.textContent='→'; body.appendChild(e); }
    const d=document.createElement('div'); d.className='gnode '+(n.cls||'tentative'); d.textContent=n.label; body.appendChild(d);
  });
}
// 📓 Live shared notebook: render the current DIRECTION (the protocol's evolving
// artifact) into the collapsible panel above the log, one row per section.
function workspaceText(sec, keys){
  for(let i=0;i<keys.length;i++){
    const v=(sec[keys[i]]||'').trim();
    if(v && v!=='-' && v.charCodeAt(0)!==8212) return v;
  }
  return '';
}
function addWorkspaceRow(box, label, value){
  const k=document.createElement('div'); k.className='wlabel'; k.textContent=label;
  const v=document.createElement('div'); v.className='wvalue';
  if(value && value.trim()){ v.textContent=value.trim(); }
  else{ v.className+=' wempty'; v.textContent='not set'; }
  box.appendChild(k); box.appendChild(v);
}
function artifactBlob(sec){
  const keys=['ACTIVE TASK','WORK QUEUE','ARTIFACT MODE','ARTIFACT COMPILER','ARTIFACTS','DESIGN VARIABLES','OPERATIONAL CRITERIA','EXPERIMENTS','OBSERVATION SETS','OPERATIONS','COMPETING MODELS','INTERPRETATIONS'];
  return keys.map(function(k){ return sec[k]||''; }).join('; ')+'; '+(ACTIVE_TASK||'')+'; '+(ARTIFACT_MODE||'')+'; '+(DIRECTION||'');
}
function rowCells(blob, label, n){
  const want=label.toLowerCase();
  const parts=(blob||'').split(';');
  for(let i=0;i<parts.length;i++){
    const p=parts[i].trim(), low=p.toLowerCase();
    if(low.indexOf(want+' |')===0 || low.indexOf(want+'|')===0){
      const bits=p.split('|').map(function(x){ return x.trim(); });
      const out=[];
      for(let j=1;j<=n;j++) out.push(bits[j]||'');
      return out;
    }
  }
  return Array(n).fill('');
}
function renderArtifactTable(zone, title, hint, headers, rows){
  const t=document.createElement('div'); t.className='artifactTitle'; t.textContent=title; zone.appendChild(t);
  const h=document.createElement('div'); h.className='artifactHint'; h.textContent=hint; zone.appendChild(h);
  const table=document.createElement('table'); table.className='artifactTable';
  const thead=document.createElement('thead'), trh=document.createElement('tr');
  headers.forEach(function(x){ const th=document.createElement('th'); th.textContent=x; trh.appendChild(th); });
  thead.appendChild(trh); table.appendChild(thead);
  const tbody=document.createElement('tbody');
  rows.forEach(function(row){
    const tr=document.createElement('tr');
    row.forEach(function(x, i){
      const td=document.createElement('td'); td.textContent=x||'';
      if(i>0){ td.contentEditable='true'; td.spellcheck=false; }
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody); zone.appendChild(table);
}
function renderLiveArtifact(sec, box){
  const blob=artifactBlob(sec);
  const wantsDV=/\\b(DV\\d+|DESIGN[_ ]VARIABLE|design variable|design-space|design space|transparency overhead|latency vs consensus|interface friction)\\b/i.test(blob);
  const wantsOC=/\\b(OC\\d+|OPERATIONAL[_ ]CRITERI(?:ON|A)|operational criterion|operational definition|failure mode|observable discriminator|evidence standard)\\b/i.test(blob);
  const wantsCG=/\\b(CG\\d+|COMPARISON[_ ]GRID|comparison grid|cost bearer|infrastructure cost|transparent cloud|local federated)\\b/i.test(blob);
  const wantsOS=/\\b(OS\\d+|OBSERVATION[_ ]SET|observation set|User Statement|Attribution|Supports|Student \\| Question Asked)\\b/i.test(blob);
  const wantsCompiled=/\\b(ARTIFACT[_ ]COMPILER|compiled|harvested|Injected Signal|Output Changed|Influence Override|Fruit\\/Painting|OS2)\\b/i.test(blob);
  if(!wantsDV && !wantsOC && !wantsCG && !wantsOS && !wantsCompiled) return;
  const zone=document.createElement('div'); zone.className='liveArtifact'; box.appendChild(zone);
  if(wantsDV){
    const dv3=/transparency overhead/i.test(blob)?'Transparency Overhead':'';
    renderArtifactTable(
      zone,
      'Current Artifact: Design Variable Register',
      'Editable cells. Accept, reject, merge, or rename proposed axes before they enter CG1 or E1.',
      ['DV','Name','Definition','Status','Affects / Blocks'],
      [
        ['DV1','Latency','','',''],
        ['DV2','Consensus','','',''],
        ['DV3',dv3,'','','']
      ]
    );
  }
  if(wantsOC){
    renderArtifactTable(
      zone,
      'Current Artifact: Operational Criterion',
      'Editable cells. Use this when a definition becomes a failure-mode test or evidence standard.',
      ['OC','Target','Failure Mode','Observable Discriminator','Status / Experiment'],
      [
        ['OC1','','','',''],
        ['OC2','','','','']
      ]
    );
  }
  if(wantsOS){
    const systems=['A','B','C'];
    renderArtifactTable(
      zone,
      'Current Artifact: OS1 Branches',
      'Editable cells. OS1 executes the artifact: one branch may support M1, one M2, and one neither or mixed.',
      ['System','User Statement','Attribution','Supports'],
      systems.map(function(label){ const cells=rowCells(blob,label,3); return [label,cells[0],cells[1],cells[2]]; })
    );
  }
  if(wantsCompiled){
    const caseCells=rowCells(blob,'Fruit/Painting',3);
    renderArtifactTable(
      zone,
      'Current Artifact: OS2 Compiled Observations',
      'Editable cells. Rows can be harvested from prose; add the next independent case before interpretation.',
      ['Case','Injected Signal','Output Changed?','Supports'],
      [
        ['Fruit/Painting',caseCells[0]||'fruit concept/signal',caseCells[1]||'No',caseCells[2]||'M2'],
        ['','','','']
      ]
    );
  }
  if(wantsCG){
    const labels=['Energy cost','Storage cost','Verification burden','Annotation labor','Cost bearer','Prediction'];
    renderArtifactTable(
      zone,
      'Current Artifact: CG1',
      'Editable cells. Once CG1 exists, execute it by deriving OS1 branch rows instead of treating it as an illustration.',
      ['Variable','M1: Transparent Cloud','M2: Local Federated'],
      labels.map(function(label){ const cells=rowCells(blob,label,2); return [label,cells[0],cells[1]]; })
    );
  }
}
function workflowStatus(sec){
  const blob=artifactBlob(sec).toLowerCase();
  if(DEADLOCKED || /\\b(workflow state\\s*:\\s*deadlocked|workflow deadlock|deadlocked)\\b/.test(blob)) return 'DEADLOCKED';
  if(ARTIFACT_MODE || /\\b(artifact mode|artifact execution|executing|populate os\\d+|os\\d+ from cg\\d+)\\b/.test(blob)) return 'EXECUTING';
  if(ACTIVE_TASK || workspaceText(sec,['ACTIVE TASK','WORK QUEUE'])) return 'BLOCKED';
  return WORKFLOW_STATE || 'IDLE';
}
function activeArtifact(sec){
  const txt=ARTIFACT_MODE || workspaceText(sec,['ARTIFACT MODE','ARTIFACT COMPILER','OPERATIONAL CRITERIA','DESIGN VARIABLES','ARTIFACTS','EXPERIMENTS','OBSERVATION SETS','OPERATIONS','ACTIVE TASK']);
  const m=/\\b(CG\\d+|OS\\d+|E\\d+|PM\\d+|CD\\d+|DV\\d+|OC\\d+|D\\d+)\\b/i.exec(txt||'');
  return m ? m[1].toUpperCase() : (txt ? txt.slice(0,70) : 'none');
}
function addStatusMatrix(box, sec){
  const grid=document.createElement('div'); grid.className='statusMatrix'; box.appendChild(grid);
  const items=[
    ['Kernel', KERNEL_HEALTH || workspaceText(sec,['KERNEL HEALTH']) || 'NORMAL'],
    ['Workflow', workflowStatus(sec)],
    ['Inquiry', workspaceText(sec,['OPERATION CHECK','INQUIRY CYCLES','FOCUS']) || 'not set'],
    ['Artifact', activeArtifact(sec)]
  ];
  items.forEach(function(pair){
    const d=document.createElement('div'); d.className='statusCell';
    const b=document.createElement('b'); b.textContent=pair[0]; d.appendChild(b);
    const s=document.createElement('span'); s.textContent=pair[1]||'not set'; d.appendChild(s);
    grid.appendChild(d);
  });
}
function renderResearchWorkspace(sec, body){
  const box=document.createElement('div'); box.className='workspace'; body.appendChild(box);
  addStatusMatrix(box, sec);
  addWorkspaceRow(box,'Work Queue',workspaceText(sec,['WORK QUEUE']) || ACTIVE_TASK);
  addWorkspaceRow(box,'Active Task',ACTIVE_TASK || workspaceText(sec,['ACTIVE TASK']));
  addWorkspaceRow(box,'Competing Models',workspaceText(sec,['COMPETING MODELS','MODEL OBJECTS']));
  addWorkspaceRow(box,'Working Definition',workspaceText(sec,['WORKING DEFINITIONS','DEFINITION REVISION','DEFINITION CONFLICTS']));
  addWorkspaceRow(box,'Design Variables',workspaceText(sec,['DESIGN VARIABLES']));
  addWorkspaceRow(box,'Operational Criteria',workspaceText(sec,['OPERATIONAL CRITERIA']));
  addWorkspaceRow(box,'Compiled Artifacts',workspaceText(sec,['ARTIFACT COMPILER']));
  addWorkspaceRow(box,'Current Artifact',ARTIFACT_MODE || workspaceText(sec,['ARTIFACT MODE','ARTIFACT COMPILER','OPERATIONAL CRITERIA','DESIGN VARIABLES','ARTIFACTS','EXPERIMENTS','OBSERVATION SETS','OPERATIONS']));
  addWorkspaceRow(box,'Next Decision',workspaceText(sec,['NEXT','KERNEL DECISION','PROMOTION GATE','TASK REVISION','DEPENDENCY SOLVER']));
  renderLiveArtifact(sec, box);
}
function renderNotebook(){
  const p=document.getElementById('notebookPanel'), b=document.getElementById('notebookBody'), st=document.getElementById('notebookStamp');
  if(!p||!b) return;
  if(!PROTO() || !DIRECTION){ p.style.display='none'; return; }
  p.style.display='block'; b.innerHTML='';
  const sec=nbSections(DIRECTION);
  renderResearchWorkspace(sec, b);
  const raw=document.createElement('details'); raw.className='rawNotebook';
  const rawSum=document.createElement('summary'); rawSum.textContent='Full ledger'; raw.appendChild(rawSum);
  DIRECTION.split('\\n').forEach(function(x){
    x=x.trim(); if(!x) return;
    const m=/^([A-Z][A-Z_ ]{2,}):\\s*(.*)$/.exec(x);
    const d=document.createElement('div'); d.className='nbrow';
    if(m){ const k=document.createElement('b'); k.textContent=m[1].replace(/_/g,' ')+': '; d.appendChild(k); d.appendChild(document.createTextNode(m[2])); }
    else{ d.textContent=x; }
    raw.appendChild(d);
  });
  b.appendChild(raw);
  if(st){ st.textContent='updated after turn '+history.length
    +(ARCS.length?' — inquiry: '+ARCS[ARCS.length-1].toLowerCase():'')
    +(MOVETYPES.length?' — last movement: '+MOVETYPES[MOVETYPES.length-1].toLowerCase():'')
    +(ACTIVE_TASK?' — active task: '+ACTIVE_TASK+(ACTIVE_TASK_ATTEMPTS?' ×'+ACTIVE_TASK_ATTEMPTS:''):'')
    +(sec['INQUIRY CYCLES'] && sec['INQUIRY CYCLES']!=='-'?' — cycles: '+sec['INQUIRY CYCLES']:'')
    +(STALL?' — barely moved ×'+STALL:''); }
  if(st && PROTOCOL_AUDIT){ st.textContent += ' | audit: '+PROTOCOL_AUDIT; }
  if(st && KERNEL_HEALTH && KERNEL_HEALTH!=='NORMAL'){ st.textContent += ' | kernel: '+KERNEL_HEALTH.toLowerCase(); }
  if(st && ARTIFACT_MODE){ st.textContent += ' | artifact mode'; }
  if(st && (ART_REQ||ART_CREATED||ART_POPULATED||ART_USED)){ st.textContent += ' | artifacts '+ART_REQ+'/'+ART_CREATED+'/'+ART_POPULATED+'/'+ART_USED; }
  renderConceptGraph();
}
let TRANSCRIPT=[], RUN_META=null;              // the written dialogue + the settings it ran with (for 💾 Save)
const logEl=document.getElementById('log');
const startBtn=document.getElementById('startBtn'), stopBtn=document.getElementById('stopBtn'), questionBtn=document.getElementById('questionBtn'), pauseBtn=document.getElementById('pauseBtn');
const saveBtn=document.getElementById('saveBtn');
const questionPanel=document.getElementById('questionPanel'), questionText=document.getElementById('questionText');
const qTypeBtn=document.getElementById('qTypeBtn'), qSpeakBtn=document.getElementById('qSpeakBtn');
const qSpeakBox=document.getElementById('qSpeakBox'), qRecordBtn=document.getElementById('qRecordBtn');
const qSubmitBtn=document.getElementById('qSubmitBtn'), qCancelBtn=document.getElementById('qCancelBtn');
const qStatus=document.getElementById('qStatus'), qRecordStatus=document.getElementById('qRecordStatus');
let PAUSED=false, PAUSE_REASON=null, PAUSE_WAITERS=[], STUDENTQ=[];
let ACTIVE_SPEECH_FINISH=null;

// iOS Safari refuses speechSynthesis unless audio was first unlocked by a real
// tap. The duet speaks each line ASYNCHRONOUSLY (after fetching the turn), which
// iOS doesn't count as a user gesture — so without this the iPhone shows the
// text but stays silent. Speaking one empty utterance during the Start tap
// unlocks audio for every automatic line that follows. (Same trick chat uses.)
let audioPrimed=false;
function primeAudio(){
  if(audioPrimed || !('speechSynthesis' in window)) return;
  try{ window.speechSynthesis.speak(new SpeechSynthesisUtterance('')); audioPrimed=true; }catch(e){}
}

// Square-bracket source tags ([Blue_Thoughts_2605.pdf]) stay visible in the
// transcript but are never read aloud (Alex, 2026-07-09).
function cleanForSpeech(t){ return (t||'').replace(/https?:\\/\\/\\S+/g,' a link ').replace(/\\[[^\\[\\]]{1,120}\\]/g,' ').replace(/[\\u{1F000}-\\u{1FFFF}\\u{2600}-\\u{27BF}]/gu,'').replace(/[*_#>~]/g,'').replace(/\\s+/g,' ').trim(); }
function buildLipFrames(text, rate){
  rate=rate||1.0; const k=1.0/rate; const words=(text.match(/[^\\s]+/g)||[]); const frames=[]; const MPC=0.060;
  for(const w of words){ const core=w.replace(/[^A-Za-z0-9\\u00C0-\\u024F]/g,''); const len=Math.max(1,core.length);
    const dur=Math.min(0.75,Math.max(0.14,len*MPC))*k; const moves=Math.max(1,Math.round(len/3)); const per=dur/moves;
    for(let i=0;i<moves;i++){ frames.push([0.6+Math.random()*0.4, per*0.6]); frames.push([0.1, per*0.4]); }
    const last=w.slice(-1); let gap=0.06; if(/[,;:)\\]]/.test(last))gap=0.22; else if(/[.!?]/.test(last))gap=0.40; frames.push([0.0,gap*k]); }
  return frames;
}
const MALE=['Daniel','Aaron','Arthur','Gordon','Microsoft David','Microsoft Mark','Google UK English Male','Google US English'];
const FEMALE=['Samantha','Victoria','Karen','Moira','Tessa','Serena','Microsoft Zira','Google UK English Female','Google US English'];
function pickVoice(cfg){
  const voices=(window.speechSynthesis&&window.speechSynthesis.getVoices())||[];
  let chosen=''; try{ chosen=localStorage.getItem('blueVoiceName_'+cfg.id)||(cfg.id==='blue'?(localStorage.getItem('blueVoiceName')||''):''); }catch(e){}
  if(chosen){ const c=voices.find(v=>v.name===chosen); if(c)return c; }
  const pl=cfg.preferFemale?FEMALE:MALE;
  for(const n of pl){ const v=voices.find(x=>x.name===n||x.name.indexOf(n)===0); if(v)return v; }
  return voices.find(x=>/^en/i.test(x.lang))||null;
}

// Voice pickers (one per robot): the device's installed voices, so you can give
// Blue and Hexia distinct, better-sounding voices than the auto pick — handy on
// iPhone, where the default female voice isn't great. The choice is saved per
// device under the SAME key pickVoice() reads (blueVoiceName_<id>), so it
// applies here and on each robot's chat page; "Automatic" clears it and falls
// back to the preferred-voice list. iOS loads voices late, so we rebuild on
// voiceschanged. (To add higher-quality voices on iPhone: Settings >
// Accessibility > Spoken Content > Voices — they then show up here.)
function supportedVoices(){
  const voices=(window.speechSynthesis&&window.speechSynthesis.getVoices())||[];
  return voices.filter(function(v){ return /^(en|fr|ru|el|da)/i.test(v.lang||''); });
}
// Speaking rate for a robot: a per-device override (the speed picker) if set,
// else the persona's configured rate. iOS Safari renders the same numeric rate
// noticeably faster than desktop, so this lets Hexia (a touch quick by design)
// be slowed to taste on the iPhone without changing how she sounds elsewhere.
function voiceRateFor(id){
  let r=''; try{ r=localStorage.getItem('blueVoiceRate_'+id)||''; }catch(e){}
  const n=parseFloat(r);
  if(r && !isNaN(n) && n>0) return n;
  return (ROBOTS[id]&&ROBOTS[id].voiceRate)||1.0;
}
function previewVoice(id, v){
  try{
    window.speechSynthesis.cancel();
    const u=new SpeechSynthesisUtterance(id==='hexia'?"Hi, I'm Hexia!":"Hi, I'm Blue!");
    const cfg=ROBOTS[id]||{}; if(v){ u.voice=v; u.lang=v.lang||'en-US'; } else { u.lang='en-US'; }
    u.rate=voiceRateFor(id); u.pitch=cfg.voicePitch||1.0;
    window.speechSynthesis.speak(u);
  }catch(e){}
}
function buildVoicePickers(){
  const voices=supportedVoices();
  [['blue','voiceBlue'],['hexia','voiceHexia']].forEach(function(pair){
    const id=pair[0], sel=document.getElementById(pair[1]); if(!sel) return;
    let saved=''; try{ saved=localStorage.getItem('blueVoiceName_'+id)||''; }catch(e){}
    sel.innerHTML='';
    const auto=document.createElement('option'); auto.value=''; auto.textContent='Automatic'; sel.appendChild(auto);
    voices.forEach(function(v){
      const o=document.createElement('option'); o.value=v.name; o.textContent=v.name+' ('+v.lang+')';
      if(v.name===saved) o.selected=true; sel.appendChild(o);
    });
    sel.onchange=function(){
      primeAudio();
      try{ if(sel.value){ localStorage.setItem('blueVoiceName_'+id, sel.value); } else { localStorage.removeItem('blueVoiceName_'+id); } }catch(e){}
      previewVoice(id, supportedVoices().find(function(x){ return x.name===sel.value; }) || pickVoice(ROBOTS[id]));
    };
  });
}
// The voice currently in effect for a robot (saved pick, else the auto choice).
function chosenVoiceFor(id){
  let nm=''; try{ nm=localStorage.getItem('blueVoiceName_'+id)||''; }catch(e){}
  if(nm){ const v=supportedVoices().find(function(x){ return x.name===nm; }); if(v) return v; }
  return pickVoice(ROBOTS[id]);
}
// Speed pickers (one per robot): a per-device speaking-rate override saved under
// blueVoiceRate_<id> and read by voiceRateFor(). "Default" clears the override.
function wireRatePickers(){
  [['blue','rateBlue'],['hexia','rateHexia']].forEach(function(pair){
    const id=pair[0], sel=document.getElementById(pair[1]); if(!sel) return;
    let saved=''; try{ saved=localStorage.getItem('blueVoiceRate_'+id)||''; }catch(e){}
    sel.value = saved || 'auto';
    if(!sel.value) sel.value='auto';      // saved value not among the options
    sel.onchange=function(){
      primeAudio();
      try{ if(sel.value && sel.value!=='auto'){ localStorage.setItem('blueVoiceRate_'+id, sel.value); } else { localStorage.removeItem('blueVoiceRate_'+id); } }catch(e){}
      previewVoice(id, chosenVoiceFor(id));
    };
  });
}
// Drive a head's lips. A head plugged into THIS device (Web Serial, via the
// shared localHeadLip) wins; else the PC browser POSTs to the server; else (a
// remote device with no local head) we stay silent and just play the voice.
function headLip(cfg,frames){
  if(localHeadLip(cfg.head, frames)) return;
  if(!DRIVES_HEADS) return;
  try{ fetch('/head/'+cfg.head+'/lip-seq',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({frames:frames})}); }catch(e){}
}
function headLipStop(cfg){
  if(localHeadLipStop(cfg.head)) return;
  if(!DRIVES_HEADS) return;
  try{ fetch('/head/'+cfg.head+'/lip',{method:'POST',headers:{'Content-Type':'application/json'},body:'{"on":false}'}); }catch(e){}
}
// Tint a head's eye LEDs to the mood of the line it's speaking (server-computed
// eye_mood {r,g,b} on the 0-10 scale), then dark it again when the turn ends —
// same local-head-else-server routing as the lips.
function headEyeSet(cfg,r,g,b){
  var body={r:r|0,g:g|0,b:b|0};
  if(localHeadControl(cfg.head,'/head/eye-color',body)) return;
  if(!DRIVES_HEADS) return;
  try{ fetch('/head/'+cfg.head+'/eye-color',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); }catch(e){}
}
function headEye(cfg,mood){ if(mood) headEyeSet(cfg,mood.r,mood.g,mood.b); }
function headEyeRest(cfg){ headEyeSet(cfg,0,0,0); }

function addTurn(cfg,text){ const d=document.createElement('div'); d.className='turn '+cfg.id;
  const w=document.createElement('div'); w.className='who'; w.textContent=cfg.name;
  const x=document.createElement('div'); x.textContent=text; d.appendChild(w); d.appendChild(x);
  TRANSCRIPT.push({kind:'turn', name:cfg.name, text:text}); saveBtn.disabled=false;
  logEl.appendChild(d); window.scrollTo(0,document.body.scrollHeight); return d; }

function speakAs(cfg,text,el,mood){ return new Promise(resolve=>{
  const useTTS=document.getElementById('speakChk').checked && ('speechSynthesis' in window);
  const rate=voiceRateFor(cfg.id);
  const frames=buildLipFrames(cleanForSpeech(text), rate);   // lips track what's actually SPOKEN
  const est=frames.reduce((s,f)=>s+f[1],0)*1000;   // ~speech duration (ms)
  let done=false, keepAlive=null;
  const finish=()=>{ if(done)return; done=true; if(ACTIVE_SPEECH_FINISH===finish) ACTIVE_SPEECH_FINISH=null; if(keepAlive){clearInterval(keepAlive);keepAlive=null;} headLipStop(cfg); headEyeRest(cfg); if(el)el.classList.remove('speaking'); resolve(); };
  ACTIVE_SPEECH_FINISH=finish;
  if(el)el.classList.add('speaking'); headLip(cfg,frames); headEye(cfg,mood);
  if(!useTTS){ setTimeout(finish, Math.max(1500, est+400)); return; }   // no audio: wait out the lip-flap
  try{
    window.speechSynthesis.cancel();
    const u=new SpeechSynthesisUtterance(cleanForSpeech(text));
    const v=pickVoice(cfg); if(v)u.voice=v; u.rate=rate; u.pitch=cfg.voicePitch||1.0; u.lang='en-US';
    u.onend=finish; u.onerror=finish;
    window.speechSynthesis.speak(u);
    // Chrome silently stops utterances after ~15s; pause+resume keeps long
    // points going to the end instead of cutting the speaker off.
    keepAlive=setInterval(function(){
      if(!window.speechSynthesis.speaking){ if(keepAlive){clearInterval(keepAlive);keepAlive=null;} }
      else { try{ window.speechSynthesis.pause(); window.speechSynthesis.resume(); }catch(e){} }
    }, 9000);
    // Hard safety so a stuck utterance can't hang the duet — generous and
    // length-based so it never fires before a normal reply finishes.
    setTimeout(finish, Math.max(20000, est*2.2 + 8000));
  }catch(e){ finish(); }
}); }

function updatePauseButton(){
  if(!pauseBtn) return;
  if(!running){
    pauseBtn.disabled=true; pauseBtn.textContent='Pause'; return;
  }
  if(PAUSE_REASON==='question'){
    pauseBtn.disabled=true; pauseBtn.textContent='Paused'; return;
  }
  pauseBtn.disabled=false;
  pauseBtn.textContent=PAUSED?'Continue':'Pause';
}
function setPaused(v, reason){
  PAUSED=!!v;
  PAUSE_REASON=PAUSED?(reason||PAUSE_REASON||'manual'):null;
  updatePauseButton();
  if(!PAUSED){
    const waiters=PAUSE_WAITERS.slice(); PAUSE_WAITERS=[];
    waiters.forEach(function(fn){ try{ fn(); }catch(e){} });
  }
}
function waitWhilePaused(){
  if(!PAUSED) return Promise.resolve();
  return new Promise(function(resolve){ PAUSE_WAITERS.push(resolve); });
}
function openQuestionPanel(){
  if(!running) return;
  questionBtn.disabled=true;
  setPaused(true,'question');
  try{ window.speechSynthesis.cancel(); }catch(e){}
  if(ACTIVE_SPEECH_FINISH) ACTIVE_SPEECH_FINISH();
  headLipStop(ROBOTS.blue); headLipStop(ROBOTS.hexia);
  questionPanel.style.display='block';
  qStatus.textContent='Dialogue paused while the question is open.';
  if(!questionText.value.trim()) questionText.value='';
  questionText.focus();
  addNote('(student question pause)');
}
function closeQuestionPanel(resume){
  questionPanel.style.display='none';
  if(qRecording) stopQuestionRecording(false);
  if(running) questionBtn.disabled=false;
  if(resume) setPaused(false);
}
function toggleManualPause(){
  if(!running || PAUSE_REASON==='question') return;
  if(PAUSED){
    setPaused(false);
    questionBtn.disabled=false;
    addNote('(duet continued)');
  }else{
    setPaused(true,'manual');
    questionBtn.disabled=true;
    addNote('(duet paused)');
  }
}
function setQuestionMode(mode){
  const speak = mode === 'speak';
  qTypeBtn.classList.toggle('active', !speak);
  qSpeakBtn.classList.toggle('active', speak);
  qSpeakBox.style.display = speak ? 'block' : 'none';
  questionText.placeholder = speak ? 'The spoken question transcript will appear here' : "Type the student's question here";
  if(!speak && qRecording) stopQuestionRecording(false);
}

let qAudioCtx=null, qMicStream=null, qSrcNode=null, qProcNode=null;
let qRecording=false, qChunks=[], qSampleRate=16000, qAutoStop=null;
async function ensureQuestionAudio(){
  const AC=window.AudioContext||window.webkitAudioContext;
  if(!navigator.mediaDevices||!navigator.mediaDevices.getUserMedia||!AC) return 'unsupported';
  try{ if(!qAudioCtx) qAudioCtx=new AC(); }catch(e){ return 'unsupported'; }
  const resumeP=(qAudioCtx.state!=='running')?qAudioCtx.resume():null;
  const mediaP=qMicStream?null:navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}}).catch(function(){
    return navigator.mediaDevices.getUserMedia({audio:true});
  });
  if(resumeP){ try{ await resumeP; }catch(e){} }
  if(qMicStream && qAudioCtx.state!=='closed') return true;
  let stream;
  try{ stream=await mediaP; }catch(e){ return 'denied'; }
  qMicStream=stream; qSampleRate=qAudioCtx.sampleRate||44100;
  qSrcNode=qAudioCtx.createMediaStreamSource(qMicStream);
  qProcNode=qAudioCtx.createScriptProcessor(4096,1,1);
  qProcNode.onaudioprocess=function(e){
    if(!qRecording) return;
    const input=e.inputBuffer.getChannelData(0);
    qChunks.push(new Float32Array(input));
  };
  const mute=qAudioCtx.createGain(); mute.gain.value=0;
  qSrcNode.connect(qProcNode); qProcNode.connect(mute); mute.connect(qAudioCtx.destination);
  window.__duetQuestionMic=[qAudioCtx,qMicStream,qSrcNode,qProcNode,mute];
  return true;
}
function qEncodeWav(chunks,sampleRate){
  let len=0; for(let i=0;i<chunks.length;i++) len+=chunks[i].length;
  const buf=new ArrayBuffer(44+len*2), view=new DataView(buf);
  function ws(off,s){ for(let i=0;i<s.length;i++) view.setUint8(off+i,s.charCodeAt(i)); }
  ws(0,'RIFF'); view.setUint32(4,36+len*2,true); ws(8,'WAVE');
  ws(12,'fmt '); view.setUint32(16,16,true); view.setUint16(20,1,true);
  view.setUint16(22,1,true); view.setUint32(24,sampleRate,true);
  view.setUint32(28,sampleRate*2,true); view.setUint16(32,2,true); view.setUint16(34,16,true);
  ws(36,'data'); view.setUint32(40,len*2,true);
  let off=44;
  for(let i=0;i<chunks.length;i++){
    const c=chunks[i];
    for(let j=0;j<c.length;j++){
      let v=c[j]; if(v>1)v=1; else if(v<-1)v=-1;
      view.setInt16(off, v<0?v*0x8000:v*0x7FFF, true); off+=2;
    }
  }
  return new Blob([view],{type:'audio/wav'});
}
async function startQuestionRecording(){
  primeAudio();
  if('speechSynthesis' in window) try{ window.speechSynthesis.cancel(); }catch(e){}
  const ok=await ensureQuestionAudio();
  if(ok==='denied'){ qRecordStatus.textContent='Microphone permission was denied.'; return; }
  if(ok!==true){ qRecordStatus.textContent=window.isSecureContext?'This browser cannot use the microphone.':'Open the secure HTTPS address to use the microphone.'; return; }
  qChunks=[]; qRecording=true;
  qRecordBtn.classList.add('recording');
  qRecordBtn.textContent='Stop recording';
  qRecordStatus.textContent='Listening... stop recording when the student is done.';
  if(qAutoStop) clearTimeout(qAutoStop);
  qAutoStop=setTimeout(function(){ stopQuestionRecording(true); }, 20000);
}
function stopQuestionRecording(submitForTranscription){
  if(qAutoStop){ clearTimeout(qAutoStop); qAutoStop=null; }
  if(!qRecording) return;
  qRecording=false;
  qRecordBtn.classList.remove('recording');
  qRecordBtn.textContent='Start recording';
  const chunks=qChunks; qChunks=[];
  if(submitForTranscription!==false) transcribeQuestion(chunks,qSampleRate);
}
async function transcribeQuestion(chunks,sampleRate){
  let total=0; for(let i=0;i<chunks.length;i++) total+=chunks[i].length;
  if(!total){ qRecordStatus.textContent='I did not hear anything. Try recording again.'; return; }
  qRecordBtn.disabled=true;
  qRecordStatus.textContent='Transcribing the question...';
  const fd=new FormData();
  fd.append('audio', qEncodeWav(chunks,sampleRate), 'question.wav');
  try{
    const res=await fetch('/stt',{method:'POST',body:fd});
    const data=await res.json().catch(function(){ return null; });
    const said=((data&&data.text)||'').trim();
    if(said){ questionText.value=said; qRecordStatus.textContent='Transcript ready. Edit it if needed, then send.'; questionText.focus(); }
    else qRecordStatus.textContent='I did not catch that. Try recording again.';
  }catch(e){
    qRecordStatus.textContent='Could not transcribe that. Try again.';
  }finally{
    qRecordBtn.disabled=false;
  }
}
function submitStudentQuestion(){
  const text=(questionText.value||'').trim();
  if(!text){ qStatus.textContent='Type or record a question first.'; questionText.focus(); return; }
  STUDENTQ.push({text:text});
  addNote('(student asks: '+text+')');
  questionText.value='';
  closeQuestionPanel(true);
}

async function oneTurn(speaker, closing){
  const topic=document.getElementById('topic').value.trim();
  const url=document.getElementById('url').value.trim();
  const noFamily=document.getElementById('noFamilyChk').checked;
  const studentQuestion=STUDENTQ.length?STUDENTQ.shift():null;
  // A queued duet email rides into THIS turn; the speaker takes it up out loud.
  const mail=(!studentQuestion && MAILQ.length)? MAILQ.shift() : null;
  if(mail && MAIL_REPLY) flushMailReply();   // a fresh email arrived before the last one collected its second voice — send what we have
  // The notebook's queued observation rides into THIS turn (unless a student
  // question or an email already owns it).
  const quietArtifact=(PROTO() && ARTIFACT_SILENCE>0 && ARTIFACT_MODE);
  const nbNote=(PROTO() && !studentQuestion && !mail && NBQ.length && !quietArtifact)? NBQ.shift() : null;
  if(quietArtifact) ARTIFACT_SILENCE--;
  let d; try{ d=await (await fetch('/duet/turn',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({speaker:speaker, topic:topic, url:url, history:history, direction:DIRECTION, mail:mail, studentQuestion:studentQuestion, notebookNote:nbNote, closing:!!closing, classroom:document.getElementById('classChk').checked, noFamily:noFamily, sources:SOURCES(), roles:fieldMap('role'), tones:fieldMap('tone'), slang:fieldMap('slang'), spice:SPICE(), protocol:PROTO(), plannedTurns:parseInt(document.getElementById('turns').value,10)||0, stalled:(PROTO() && STALL>=2), monotony:(PROTO()?MONO():''), arcStuck:(PROTO()?ARCSTUCK():''), operationMissed:(PROTO() && OPFAILS>0), validationRejected:(PROTO() && GATEFAILS>0), promotionRejected:(PROTO() && PROMOTIONFAILS>0), kernelDenied:(PROTO() && KERNELFAILS>0), kernelDeadlocked:(PROTO() && DEADLOCKED), kernelHealth:(PROTO()?KERNEL_HEALTH:''), activeTask:(PROTO()?ACTIVE_TASK:''), artifactPlan:(PROTO()?ARTIFACT_PLAN:''), artifactMode:(PROTO()?ARTIFACT_MODE:''), activeTaskAttempts:(PROTO()?ACTIVE_TASK_ATTEMPTS:0), research:document.getElementById('researchChk').checked, wiki:document.getElementById('wikiChk').checked})})).json(); }catch(e){ if(mail) MAILQ.unshift(mail); if(studentQuestion) STUDENTQ.unshift(studentQuestion); if(nbNote) NBQ.unshift(nbNote); return false; }
  if(!d||!d.text){ if(mail) MAILQ.unshift(mail); if(studentQuestion) STUDENTQ.unshift(studentQuestion); if(nbNote) NBQ.unshift(nbNote); return false; }
  if(!studentQuestion && !mail){
    if(PAUSED){
      await waitWhilePaused();
      if(!running) return null;
    }
    if(STUDENTQ.length) return 'defer';  // a question arrived while this ordinary line was being generated
  }
  const cfg=ROBOTS[speaker];
  // The email enters the shared history as an event, so the OTHER robot (and the
  // take-stock bearing) see exactly what was written, not just the paraphrase.
  if(studentQuestion){ history.push({speaker:'question', text:studentQuestion.text}); }
  if(mail){ history.push({speaker:'mail', text:'From '+mail.from_name+' — "'+mail.subject+'": '+mail.body}); }
  // The notebook spoke: it enters the shared history as its own voice, so BOTH
  // robots (and the keeper) see exactly what it said.
  if(nbNote){ history.push({speaker:'notebook', text:nbNote}); addNote('(📓 the notebook observes: '+nbNote+')'); }
  // 🔬 deep-dive protocol: surface phase changes and Builder/Examiner swaps as notes.
  if(d.phase && d.phase!==LAST_PHASE){ LAST_PHASE=d.phase; addNote('(🔬 '+d.phase+' phase — '+(d.phaseNote||'')+')'); }
  if(d.job){ const b=(d.job==='builder')?speaker:(speaker==='blue'?'hexia':'blue');
    if(b!==LAST_BUILDER){ LAST_BUILDER=b; addNote('(🔬 '+ROBOTS[b].name+' builds, '+ROBOTS[b==='blue'?'hexia':'blue'].name+' examines)'); } }
  if(d.beat==='conclusions'){ addNote('('+ROBOTS[speaker].name+' pauses to weigh what they can conclude so far)'); }
  if(d.stallBreak){ addNote('(🔬 stall break — '+ROBOTS[speaker].name+' must bring new ground this turn)'); }
  if(d.monotonyBreak){ addNote('(🔬 '+ROBOTS[speaker].name+' must change the kind of move — no more '+d.monotonyBreak.toLowerCase()+'s)'); }
  if(d.arcBreak){ addNote('(🔬 inquiry intervention — '+ROBOTS[speaker].name+' must advance it past '+d.arcBreak.toLowerCase()+')'); }
  const el=addTurn(cfg,d.text); history.push({speaker:speaker, text:d.text});
  if(mail){ MAIL_REPLY={mail:mail, lines:[{name:d.name, text:d.text}]}; }
  else if(MAIL_REPLY && MAIL_REPLY.lines.length===1){ MAIL_REPLY.lines.push({name:d.name, text:d.text}); flushMailReply(); }
  maybeReflect();                 // take stock of the direction in the background, while this head speaks
  await speakAs(cfg,d.text,el,d.eye_mood); return true;
}
// ---- Live duet mail: email with "duet" in the subject joins the conversation ----
// While a duet runs (and the checkbox is on), poll Blue's inbox in the background;
// a new matching email is queued, barged into the next turn, and after BOTH robots
// have spoken to it their lines are mailed back to the sender in-thread.
let MAILQ=[], MAIL_REPLY=null, mailTimer=null;
function mailOn(){ const c=document.getElementById('mailChk'); return !!(c && c.checked); }
function pollMail(){
  if(!running || !mailOn()) return;
  fetch('/duet/mail/check',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
    .then(function(r){ return r.json(); })
    .then(function(j){
      if(!j || !j.ok || !j.mails || !j.mails.length) return;
      for(let i=0;i<j.mails.length;i++){
        MAILQ.push(j.mails[i]);
        addNote('(📧 mail from '+j.mails[i].from_name+' — "'+j.mails[i].subject+'" — queued for the next turn)');
      }
    }).catch(function(){});
}
function flushMailReply(){
  const pr=MAIL_REPLY; MAIL_REPLY=null;
  if(!pr || !pr.lines.length) return;
  fetch('/duet/mail/reply',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({id:pr.mail.id, thread_id:pr.mail.thread_id, message_id_header:pr.mail.message_id_header,
                             from_email:pr.mail.from_email, subject:pr.mail.subject, lines:pr.lines})})
    .then(function(r){ return r.json(); })
    .then(function(j){
      if(j&&j.ok) addNote('(📧 their answer was emailed back to '+pr.mail.from_name+')');
      else addNote('(📧 could not email the answer back'+(j&&j.error?': '+j.error:'')+')');
    }).catch(function(){});
}
// Every few turns, step back and refresh the conversation's bearing (DIRECTION):
// where it's actually gotten and where it could go next. Fired without awaiting so
// it overlaps the current head's speech and never delays a turn; the NEXT turn POSTs
// the updated bearing. This is what lets the duet develop a line of thought and the
// two robots' views move, instead of just volleying replies to the last point.
function maybeReflect(){
  const n=history.length, proto=PROTO();
  // Not in the opening; take stock often enough to keep an arc. In 🔬 deep-dive
  // mode the notebook is the point, so it refreshes every other turn (still
  // backgrounded under the head's speech, so it costs no turn time).
  if(n<3 || n%(proto?2:3)!==0) return;
  const topic=document.getElementById('topic').value.trim();
  const url=document.getElementById('url').value.trim();
  fetch('/duet/reflect',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({history:history, direction:DIRECTION, topic:topic, url:url, protocol:proto, roles:fieldMap('role'), sources:SOURCES(), noFamily:document.getElementById('noFamilyChk').checked})})
    .then(function(r){ return r.json(); })
    .then(function(j){
      if(!j || typeof j.direction!=='string' || !j.direction.trim()) return;
      DIRECTION=j.direction;
      const compiledArtifact=!!(j.artifactCompiler && ['COMPILED','HARVESTED'].indexOf(j.artifactCompiler.status)>=0);
      // Mechanical stall counter (protocol): the server diffed the new notebook
      // against the previous one. Two barely-moved reflects in a row => the next
      // turns are FORCED to break new ground (oneTurn sends stalled:true).
      if(proto){
        REFLECTS++;
        if(j.stalled){ STALL++; if(running) addNote('(📓 the notebook barely moved'+(STALL>=2?' — forcing new ground next turn':'')+')'); }
        else STALL=0;
        // Track HOW it moved; a NONE clears the streak (the stall machinery owns that case).
        if(j.movement && j.movement.type){
          if(j.movement.type==='NONE'){ MOVETYPES.length=0; }
          else{
            MOVETYPES.push(j.movement.type);
            if(MOVETYPES.length>6) MOVETYPES.shift();
            if(MONO() && running) addNote('(📓 movement monotony — '+j.movement.type.toLowerCase()+' three reflects running; a different kind of move is coming)');
          }
        }
        // Track WHERE the inquiry is (inferred, not scheduled); note stage changes.
        if(j.arc && j.arc.stage){
          const prevArc=ARCS.length?ARCS[ARCS.length-1]:'';
          ARCS.push(j.arc.stage);
          if(ARCS.length>6) ARCS.shift();
          if(running && j.arc.stage!==prevArc) addNote('(📓 the inquiry has entered its '+j.arc.stage.toLowerCase()+' stage)');
          else if(running && ARCSTUCK()) addNote('(📓 the inquiry has sat in '+j.arc.stage.toLowerCase()+' for a while — pushing it forward)');
        }
        if(j.activeTask && typeof j.activeTask.active!=='undefined'){
          if(j.activeTask.active){
            const nextTask=(j.activeTask.note||j.activeTask.id||'active task').trim();
            ACTIVE_TASK_ATTEMPTS=(ACTIVE_TASK && nextTask===ACTIVE_TASK)?ACTIVE_TASK_ATTEMPTS+1:1;
            if(!ACTIVE_TASK || nextTask!==ACTIVE_TASK) ART_REQ++;
            ACTIVE_TASK=nextTask;
            WORKFLOW_STATE=/\b(execut|observe|observation|populate|OS\d+|E\d+)\b/i.test(ACTIVE_TASK)?'EXECUTING':'BLOCKED';
            const taskMsg='ACTIVE TASK BLOCKING: '+ACTIVE_TASK+'. Attempts '+ACTIVE_TASK_ATTEMPTS+'. No new hypotheses, definitions, examples, or paradigm challenges. If CG1 exists, execute through OS1 branch rows (System | User Statement | Attribution | Supports) before interpreting. If an experiment is designed, execute only: Input, Prediction, Observation table, Outcome. Otherwise advance one legal lifecycle step or mark FAILED with a reason.';
            if(NBQ.indexOf(taskMsg)<0) NBQ.push(taskMsg);
            if(/\b(execut|observe|observation|populate|OS\d+|E\d+)\b/i.test(ACTIVE_TASK)){
              ARTIFACT_MODE=ACTIVE_TASK;
              ARTIFACT_SILENCE=2;
            }
            if(running) addNote('(📓 active task blocking — '+ACTIVE_TASK+' ×'+ACTIVE_TASK_ATTEMPTS+')');
          } else if(ACTIVE_TASK){
            ACTIVE_TASK='';
            ACTIVE_TASK_ATTEMPTS=0;
            ARTIFACT_MODE='';
            ARTIFACT_SILENCE=0;
            WORKFLOW_STATE='IDLE';
            LAST_RECOVERY_TURN=history.length;
            if(running) addNote('(📓 active task cleared)');
          }
        }
        if(compiledArtifact){
          KERNELFAILS=0; OPFAILS=0; DEADLOCKED=false; KERNEL_HEALTH='NORMAL';
          WORKFLOW_STATE='EXECUTING'; LAST_RECOVERY_TURN=history.length;
          ARTIFACT_MODE=(j.artifactCompiler.note||'compiled observation set').trim();
          ARTIFACT_SILENCE=1;
          const compilerMsg='Artifact compiler harvested prose into a row: '+(j.artifactCompiler.note||'compiled observation row')+'. Continue from the compiled artifact; ask only for missing fields or the next independent case before interpretation.';
          if(NBQ.indexOf(compilerMsg)<0){ NBQ.push(compilerMsg); ART_POPULATED++; }
          if(PAUSED && PAUSE_REASON==='kernel') setPaused(false);
          if(running) addNote('(artifact compiler - row harvested)');
        }
        if(j.kernelDecision && j.kernelDecision.status){
          if(compiledArtifact && ['DENIED','DEADLOCKED','PAUSED','SUSPENDED','PENDING'].indexOf(j.kernelDecision.status)>=0){
            KERNELFAILS=0; KERNEL_HEALTH='NORMAL'; DEADLOCKED=false; WORKFLOW_STATE='EXECUTING';
          } else if(j.kernelDecision.status==='DENIED'){
            KERNELFAILS++;
            const denied='PROTOCOL VIOLATION: blocked transition attempt '+KERNELFAILS+'; '+(j.kernelDecision.note||'state transition illegal or prerequisite missing')+'. Perform only the allowed next transition; do not discuss the denial.';
            NBQ.push(denied);
            if(running) addNote('(📓 request denied — '+(j.kernelDecision.note||'kernel prerequisite missing')+')');
          } else if(j.kernelDecision.status==='DEADLOCKED'){
            DEADLOCKED=true; WORKFLOW_STATE='DEADLOCKED';
            const dead='DEADLOCK DETECTED: '+(j.kernelDecision.note||'workflow has mutually blocking requirements')+'. Set aside the blocked object and resume its prerequisite before any further execution demand; do not narrate kernel state.';
            if(NBQ.indexOf(dead)<0) NBQ.push(dead);
            if(running) addNote('(kernel deadlocked - dependency solver required)');
          } else if(j.kernelDecision.status==='PAUSED'){
            KERNEL_HEALTH='PAUSED';
            const paused='INQUIRY PAUSED: '+(j.kernelDecision.note||'kernel paused until a required artifact is accepted')+'. Resume when the required artifact is accepted.';
            if(NBQ.indexOf(paused)<0) NBQ.push(paused);
            if(running){ addNote('(inquiry paused - artifact required before continuing)'); setPaused(true,'kernel'); }
          } else if(j.kernelDecision.status==='SUSPENDED'){
            const suspended='KERNEL SUSPENSION: '+(j.kernelDecision.note||'execution blocked by concept instability')+'. Required operation: concept audit / definition resolution before execution resumes.';
            if(NBQ.indexOf(suspended)<0) NBQ.push(suspended);
            if(running) addNote('(kernel suspended - concept resolution required)');
          } else if(j.kernelDecision.status==='DEFERRED'){
            KERNELFAILS=0;
            ARTIFACT_PLAN=j.kernelDecision.note||ARTIFACT_PLAN;
            const deferred='Task deferred to prerequisite: '+(j.kernelDecision.note||'build the prerequisite artifact, then resume the original target')+'. Do not treat this as failure; build the prerequisite artifact next.';
            if(NBQ.indexOf(deferred)<0) NBQ.push(deferred);
            if(running) addNote('(task revised - prerequisite artifact first)');
          } else if(j.kernelDecision.status==='ACCEPTED' || j.kernelDecision.status==='NONE'){
            KERNELFAILS=0;
          }
        }
        if(j.kernelHealth && j.kernelHealth.status){
          if(compiledArtifact && ['DEADLOCKED','PAUSED','WARNING'].indexOf(j.kernelHealth.status)>=0){
            KERNEL_HEALTH='NORMAL'; DEADLOCKED=false;
          } else if(j.kernelHealth.status==='DEADLOCKED'){
            DEADLOCKED=true; WORKFLOW_STATE='DEADLOCKED'; KERNEL_HEALTH='NORMAL';
          } else {
            KERNEL_HEALTH=j.kernelHealth.status;
          }
          const healthMsg=(DEADLOCKED?'WORKFLOW STATE: '+WORKFLOW_STATE+'. ':'KERNEL HEALTH: '+KERNEL_HEALTH+'. ')+(j.kernelHealth.note||'');
          if((KERNEL_HEALTH!=='NORMAL' || DEADLOCKED) && NBQ.indexOf(healthMsg)<0) NBQ.push(healthMsg);
          if(running && DEADLOCKED) addNote('(workflow deadlocked - kernel still tracking state)');
        }
        if(j.inquiryPause && j.inquiryPause.active && !compiledArtifact){
          KERNEL_HEALTH='PAUSED';
          const pauseMsg='INQUIRY PAUSED: '+(j.inquiryPause.note||'required artifact not accepted yet')+'. Resume when the required artifact is accepted.';
          if(NBQ.indexOf(pauseMsg)<0) NBQ.push(pauseMsg);
          if(running){ addNote('(inquiry paused - '+(j.inquiryPause.note||'awaiting artifact')+')'); setPaused(true,'kernel'); }
        }
        if(j.protocolAudit && j.protocolAudit.note){
          PROTOCOL_AUDIT=j.protocolAudit.note;
          const auditMsg='PROTOCOL AUDIT: '+PROTOCOL_AUDIT+'. Compress repeated violations and perform only the legal next operation.';
          if(NBQ.indexOf(auditMsg)<0) NBQ.push(auditMsg);
          if(running) addNote('(protocol audit - '+PROTOCOL_AUDIT+')');
        } else if(!KERNELFAILS && !OPFAILS && !GATEFAILS && !PROMOTIONFAILS) {
          PROTOCOL_AUDIT='';
        }
        if(j.conceptConflict && j.conceptConflict.active){
          const conceptMsg='CONCEPT AUDIT: '+(j.conceptConflict.note||'definition instability blocks the current experiment')+'. Suspend experiment execution until the term has current definition, alternative D IDs, dependencies, counterexamples, stress level, stability, and a resolution operation.';
          if(NBQ.indexOf(conceptMsg)<0) NBQ.push(conceptMsg);
          if(running) addNote('(concept audit - definition instability blocks execution)');
        }
        if(j.dependencySolver && j.dependencySolver.note){
          const solverMsg='Recovery prerequisite: '+j.dependencySolver.note+'. Execute the next resolvable prerequisite before returning to the blocked object.';
          if(NBQ.indexOf(solverMsg)<0) NBQ.push(solverMsg);
          if(running) addNote('(dependency solver - prerequisite selected)');
        }
        if(j.artifactPlanner && j.artifactPlanner.active){
          ARTIFACT_PLAN=(j.artifactPlanner.note||'').trim();
          const planMsg='Artifact construction order: '+(ARTIFACT_PLAN||'choose the smallest missing artifact')+'. If the target artifact is ready, build it exactly; if not, build only the prerequisite and state when the target resumes.';
          if(NBQ.indexOf(planMsg)<0) NBQ.push(planMsg);
          if(running) addNote('(artifact planner - '+(j.artifactPlanner.status||'planned').toLowerCase()+')');
        }
        if(j.artifactCompiler && j.artifactCompiler.status==='NEEDS_HUMAN'){
          const needsMsg='Artifact compiler cannot infer one required field: '+(j.artifactCompiler.note||'missing row field')+'. Ask only for that missing field; do not restart the artifact or pause the whole inquiry.';
          if(NBQ.indexOf(needsMsg)<0) NBQ.push(needsMsg);
          if(running) addNote('(artifact compiler - missing field only)');
        }
        if(j.artifactMode && j.artifactMode.active){
          ARTIFACT_MODE=(j.artifactMode.note||ACTIVE_TASK||'active artifact').trim();
          ARTIFACT_SILENCE=2;
          WORKFLOW_STATE='EXECUTING';
          if(running) addNote('(artifact mode locked - notebook quiet while cells are filled)');
        }
        if(j.recoveryStrategy && j.recoveryStrategy.note){
          const strategyMsg='RECOVERY STRATEGY: '+j.recoveryStrategy.note+'. Produce the exact requested artifact, not another audit.';
          if(NBQ.indexOf(strategyMsg)<0) NBQ.push(strategyMsg);
          if(running) addNote('(recovery strategy - '+j.recoveryStrategy.note+')');
        }
        if(j.operationCheck && j.operationCheck.status){
          if(j.operationCheck.status==='MISSED'){
            OPFAILS++;
            if(!DEADLOCKED) WORKFLOW_STATE='BLOCKED';
            const miss='Operation not completed: produce the explicit artifact now. If CG1 is instantiated, create/populate OS1 with branch rows; otherwise use System A/System B, variables, prediction, result, or confidence change. Hypothesis and definition status remain unchanged. No metaphor-only answer.';
            NBQ.push(miss);
            if(running) addNote('(📓 operation missed — requiring an explicit artifact next turn)');
          } else if(j.operationCheck.status==='COMPLETED'){
            OPFAILS=0;
            ART_CREATED++;
            if(ARTIFACT_MODE){ ART_POPULATED++; ARTIFACT_MODE=''; ARTIFACT_SILENCE=0; }
            if(!ACTIVE_TASK) WORKFLOW_STATE='IDLE';
            LAST_RECOVERY_TURN=history.length;
            const useArtifact='Artifact created or completed: do not abandon it. Next, test it, use it as evidence, build a discriminator, submit the proposed edit to validation, or link the named artifact ID to a dependency.';
            NBQ.push(useArtifact);
            if(running) addNote('(📓 operation completed — '+(j.operationCheck.note||'artifact recorded')+')');
          } else if(j.operationCheck.status==='FAILED'){
            OPFAILS=0;
            if(ARTIFACT_MODE){ ARTIFACT_MODE=''; ARTIFACT_SILENCE=0; }
            WORKFLOW_STATE='RECOVERING';
            const failed='Experiment failed: record why it failed, preserve salvageable data (primary result, secondary observation, unexpected finding, redesign implication), and do not let it change theory confidence unless interpretation is warranted.';
            NBQ.push(failed);
            if(running) addNote('(📓 experiment failed — recording failure as evidence)');
          } else if(['PROPOSED','DESIGNED','EXECUTING','OBSERVED','INTERPRETED','OPERATIONALIZED','RUNNING','EXECUTED','PENDING'].indexOf(j.operationCheck.status)>=0){
            OPFAILS=0;
            WORKFLOW_STATE=(j.operationCheck.status==='EXECUTING' || j.operationCheck.status==='RUNNING' || j.operationCheck.status==='OPERATIONALIZED')?'EXECUTING':'BLOCKED';
            if(j.operationCheck.status==='OBSERVED' || j.operationCheck.status==='EXECUTED'){
              ART_POPULATED++;
              if(ARTIFACT_MODE){ ARTIFACT_MODE=''; ARTIFACT_SILENCE=0; }
            }
            const inProgress='Operation in progress ('+j.operationCheck.status.toLowerCase()+'): continue the same task to its next lifecycle state before introducing new hypotheses or definitions.';
            if(NBQ.indexOf(inProgress)<0) NBQ.push(inProgress);
            if(running) addNote('(📓 operation '+j.operationCheck.status.toLowerCase()+' — continuing task)');
          } else if(j.operationCheck.status==='NONE'){
            OPFAILS=0;
          }
        }
        if(j.validationGate && j.validationGate.status){
          if(j.validationGate.status==='REJECTED'){
            GATEFAILS++;
            const rejected='Validation gate rejected: do not revise the hypothesis, definition, or status yet. Complete the missing comparison, prediction, discriminator, experiment execution/interpretation, dependency update, or evidence provenance first.';
            NBQ.push(rejected);
            if(running) addNote('(📓 validation gate rejected — status unchanged until evidence is earned)');
          } else if(j.validationGate.status==='ACCEPTED'){
            GATEFAILS=0;
            ART_USED++;
            LAST_RECOVERY_TURN=history.length;
            const accepted='Notebook edit accepted: record the commit consequence by naming affected objects, dependencies, and the evidence that justified the change.';
            NBQ.push(accepted);
            if(running) addNote('(📓 validation gate accepted — commit the consequence)');
          } else if(j.validationGate.status==='NONE'){
            GATEFAILS=0;
          }
        }
        if(j.promotionGate && j.promotionGate.status){
          if(j.promotionGate.status==='REJECTED'){
            PROMOTIONFAILS++;
            const promoRejected='Promotion gate rejected: keep the candidate INTERESTING/SUGGESTIVE, split observation from interpretation, preserve alternative interpretations, and add the next independent replication or discriminator before any SUPPORTED status.';
            if(NBQ.indexOf(promoRejected)<0) NBQ.push(promoRejected);
            if(running) addNote('(ðŸ““ promotion gate rejected â€” replication required before support)');
          } else if(j.promotionGate.status==='ACCEPTED'){
            PROMOTIONFAILS=0;
            ART_USED++;
            LAST_RECOVERY_TURN=history.length;
            const promoAccepted='Promotion gate accepted: record which independent replications/discriminators earned the status change and update dependent causal claims.';
            if(NBQ.indexOf(promoAccepted)<0) NBQ.push(promoAccepted);
            if(running) addNote('(ðŸ““ promotion gate accepted â€” commit earned status)');
          } else if(j.promotionGate.status==='PENDING'){
            const promoPending='Promotion pending: name the candidate ladder state, count independent replications/discriminators, and run the next missing discriminator before promotion.';
            if(NBQ.indexOf(promoPending)<0) NBQ.push(promoPending);
            if(running) addNote('(ðŸ““ promotion pending â€” candidate still under replication)');
          } else if(j.promotionGate.status==='NONE'){
            PROMOTIONFAILS=0;
          }
        }
        if(j.paradigmCheck && j.paradigmCheck.status==='MISSED'){
          const pmiss='Paradigm challenge not completed: choose one rival framework and use only its ontology first, then give the separating prediction. Do not translate the current theory into new words.';
          NBQ.push(pmiss);
          if(running) addNote('(📓 paradigm challenge missed — requiring a stricter rival ontology next turn)');
        }
        if(updateKernelDeadlock() && running) addNote('(workflow deadlock detected - recovery operation next)');
        // The notebook's own voice: queue earned observations and periodic
        // progress checks for upcoming turns.
        if(!ARTIFACT_MODE && j.observation && j.observation!==LAST_OBS){
          LAST_OBS=j.observation;
          NBQ.push(j.observation);
        }
        if(!ARTIFACT_MODE && REFLECTS>0 && REFLECTS%4===0){
          const progressCheck='Which inquiry cycle advanced: task, experiment, observation, or notebook revision? If none, name the blocking lifecycle step still missing.';
          if(NBQ.indexOf(progressCheck)<0){
            NBQ.push(progressCheck);
            if(running) addNote('(📓 progress check queued — the next turn must name the cycle step advanced or the blocking step still missing)');
          }
        }
        if(!ARTIFACT_MODE && REFLECTS>0 && REFLECTS%6===0){
          const paradigmCheck='META: suppose the current leading model is false. Choose exactly one rival framework for one turn only - cognitive psychology, actor-network theory, distributed cognition, cybernetics, information economics, or media ecology - explain the same observations only from that framework, then name the prediction that would separate it from the current one.';
          if(NBQ.indexOf(paradigmCheck)<0){
            NBQ.push(paradigmCheck);
            if(running) addNote('(📓 paradigm challenge queued — the next turn must test a rival framework)');
          }
        }
        if(!ARTIFACT_MODE && REFLECTS>0 && REFLECTS%5===0){
          const editMode='EDIT MODE: introduce no new concepts. Only delete, revise, split, merge, archive, or re-evaluate existing notebook objects by ID. Identify at least one redundant concept or dependency consequence.';
          if(NBQ.indexOf(editMode)<0){
            NBQ.push(editMode);
            if(running) addNote('(📓 edit mode queued — compress or revise existing objects only)');
          }
        }
        if(NBQ.length>7) NBQ=NBQ.slice(-7);
      }
      renderNotebook();
      // Surface the developing direction unobtrusively, so the self-reflection is visible.
      const m=/NEXT:\\s*(.+)/i.exec(DIRECTION);
      if(m && running){
        const mv=(proto && j.movement && j.movement.type && j.movement.type!=='NONE')?('advanced by '+j.movement.type.toLowerCase()+'; '):'';
        addNote('(they take stock — '+mv+'where this is heading: '+m[1].trim()+')');
      }
    }).catch(function(){});
}
async function run(){
  running=true; history=[]; DIRECTION=''; LAST_PHASE=''; LAST_BUILDER=''; STALL=0; MOVETYPES=[]; ARCS=[]; NBQ=[]; LAST_OBS=''; REFLECTS=0; OPFAILS=0; GATEFAILS=0; PROMOTIONFAILS=0; KERNELFAILS=0; PROTOCOL_AUDIT=''; KERNEL_HEALTH='NORMAL'; WORKFLOW_STATE='IDLE'; DEADLOCKED=false; LAST_RECOVERY_TURN=0; ACTIVE_TASK=''; ACTIVE_TASK_ATTEMPTS=0; ARTIFACT_PLAN=''; ARTIFACT_MODE=''; ARTIFACT_SILENCE=0; ART_REQ=0; ART_CREATED=0; ART_POPULATED=0; ART_USED=0; logEl.innerHTML=''; renderNotebook(); startBtn.disabled=true; stopBtn.disabled=false; questionBtn.disabled=false; pauseBtn.disabled=false;
  setPaused(false); STUDENTQ=[];
  TRANSCRIPT=[]; saveBtn.disabled=true;
  // A bare link pasted into the topic box IS the link — move it over visibly.
  const topicEl=document.getElementById('topic'), urlEl=document.getElementById('url');
  if(!urlEl.value.trim() && /^https?:\\/\\/\\S+$/.test(topicEl.value.trim())){ urlEl.value=topicEl.value.trim(); topicEl.value=''; }
  const url=urlEl.value.trim();
  // Snapshot the settings this run started with — the transcript header (💾 Save)
  // records them even if the fields are edited afterwards.
  RUN_META={ when:new Date().toLocaleString(), topic:topicEl.value.trim(), url:url,
             roles:fieldMap('role'), tones:fieldMap('tone'), slang:fieldMap('slang'),
             sources:SOURCES(), spice:SPICE(),
             classroom:document.getElementById('classChk').checked,
             protocol:PROTO(),
             noFamily:document.getElementById('noFamilyChk').checked,
             research:document.getElementById('researchChk').checked,
             wiki:document.getElementById('wikiChk').checked,
             mail:mailOn() };
  if(url){
    addNote('(reading the link…)');
    let r=null;
    try{ r=await (await fetch('/duet/fetch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url})})).json(); }catch(e){}
    if(!running){ return; }
    if(!r||!r.ok){ addNote("(couldn't read that link"+(r&&r.error?': '+r.error:'')+" — fix it or clear the field)"); stop(); return; }
    addNote("(they've "+(r.kind==='video'?'watched':'read')+': '+(r.title||url)+')');
  }
  if(document.getElementById('researchChk').checked){
    addNote('(researching the subject thoroughly — several searches, reading the best pages…)');
    let rr=null;
    try{ rr=await (await fetch('/duet/research',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topic:topicEl.value.trim(), url:url, roles:fieldMap('role')})})).json(); }catch(e){}
    if(!running){ return; }
    if(rr&&rr.ok){
      if(rr.queries&&rr.queries.length>1){ addNote('(searched: '+rr.queries.join(' · ')+')'); }
      addNote("(they've read up on it: "+((rr.titles&&rr.titles.length)?rr.titles.slice(0,4).join(' · '):rr.query)+')');
    }
    else{ addNote("(web research came up empty"+(rr&&rr.error?': '+rr.error:'')+" — they'll wing it)"); }
  }
  const srcSel=SOURCES();
  if((srcSel.blue||[]).length || (srcSel.hexia||[]).length){
    // Digest the checked documents' ARGUMENTS up front (cached after the first
    // time), so every turn can engage the works' claims, not just stray passages.
    addNote('(studying the readings…)');
    let sr=null;
    try{ sr=await (await fetch('/duet/readings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sources:srcSel})})).json(); }catch(e){}
    if(!running){ return; }
    if(sr&&sr.ok){ addNote("(they've studied: "+(sr.read||[]).join(' · ')+((sr.failed&&sr.failed.length)?" — couldn't digest: "+sr.failed.join(' · '):'')+')'); }
    else{ addNote("(couldn't digest the readings — they'll lean on retrieved passages alone)"); }
  }
  if(document.getElementById('wikiChk').checked){
    addNote('(reading Wikipedia…)');
    let wr=null;
    try{ wr=await (await fetch('/duet/wikipedia',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topic:topicEl.value.trim(), url:url, roles:fieldMap('role')})})).json(); }catch(e){}
    if(!running){ return; }
    if(wr&&wr.ok){ addNote("(they've read up on Wikipedia: "+((wr.titles&&wr.titles.length)?wr.titles.join(' · '):wr.query)+')'); }
    else{ addNote("(no Wikipedia match"+(wr&&wr.error?': '+wr.error:'')+" — they'll wing it)"); }
  }
  MAILQ=[]; MAIL_REPLY=null;
  if(mailOn()){
    // Baseline first: mail already sitting in the inbox predates this duet and
    // must not barge in stale. Only NEW arrivals join the conversation.
    try{ await fetch('/duet/mail/check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reset:true})}); }catch(e){}
    if(!running){ return; }
    addNote('(📧 watching the inbox — email with duet in the subject joins the conversation)');
    mailTimer=setInterval(pollMail, 8000);
  }
  let turns=parseInt(document.getElementById('turns').value,10); if(isNaN(turns))turns=6;   // 0 = until you press Stop
  let speaker=document.getElementById('starter').value;
  for(let i=0; running && (turns===0 || i<turns); i++){
    await waitWhilePaused();
    if(!running) break;
    const ok=await oneTurn(speaker, turns>0 && i>=turns-2);
    if(!ok){ addNote(ok===false?'(…lost the thread — is LM Studio running?)':''); break; }
    if(ok==='defer'){ i--; continue; }
    speaker=(speaker==='blue')?'hexia':'blue';
  }
  stop();
}
function addNote(t){ if(!t)return; TRANSCRIPT.push({kind:'note', text:t}); const d=document.createElement('div'); d.className='muted'; d.textContent=t; logEl.appendChild(d); }
function stop(){ running=false; setPaused(false); if(qRecording) stopQuestionRecording(false); if(questionPanel) questionPanel.style.display='none'; if(mailTimer){ clearInterval(mailTimer); mailTimer=null; } flushMailReply(); try{ window.speechSynthesis.cancel(); }catch(e){} if(ACTIVE_SPEECH_FINISH) ACTIVE_SPEECH_FINISH(); headLipStop(ROBOTS.blue); headLipStop(ROBOTS.hexia); startBtn.disabled=false; stopBtn.disabled=true; questionBtn.disabled=true; pauseBtn.disabled=true; pauseBtn.textContent='Pause'; }
startBtn.addEventListener('click', function(){ primeAudio(); run(); });
stopBtn.addEventListener('click', stop);
questionBtn.addEventListener('click', openQuestionPanel);
pauseBtn.addEventListener('click', toggleManualPause);
qTypeBtn.addEventListener('click', function(){ setQuestionMode('type'); });
qSpeakBtn.addEventListener('click', function(){ setQuestionMode('speak'); try{ fetch('/stt/warmup'); }catch(e){} });
qRecordBtn.addEventListener('click', function(){ qRecording ? stopQuestionRecording(true) : startQuestionRecording(); });
qSubmitBtn.addEventListener('click', submitStudentQuestion);
qCancelBtn.addEventListener('click', function(){ questionText.value=''; closeQuestionPanel(true); addNote('(student question cancelled)'); });
// ---- 💾 Save: download the written dialogue as a Markdown file, headed by the
// settings the run started with (so a class session can be re-created later).
function saveTranscript(){
  if(!TRANSCRIPT.length) return;
  const m=RUN_META||{};
  const L=['# Blue & Hexia — duet transcript','*'+(m.when||new Date().toLocaleString())+'*',''];
  if(m.topic) L.push('- **Topic:** '+m.topic);
  if(m.url) L.push('- **Link:** '+m.url);
  ['blue','hexia'].forEach(function(id){
    const bits=[];
    if((m.roles||{})[id]) bits.push('role: '+m.roles[id]);
    if((m.tones||{})[id]) bits.push('tone: '+m.tones[id]);
    if((m.slang||{})[id]) bits.push('slang: '+m.slang[id]);
    const src=((m.sources||{})[id])||[];
    if(src.length) bits.push('draws on: '+src.join('; '));
    if(bits.length) L.push('- **'+ROBOTS[id].name+':** '+bits.join(' — '));
  });
  const flags=[];
  if(m.classroom) flags.push('classroom mode');
  if(m.protocol) flags.push('🔬 deep-dive protocol');
  if(m.noFamily) flags.push('no family refs');
  if(m.research) flags.push('web research');
  if(m.wiki) flags.push('Wikipedia');
  if(m.mail) flags.push('duet mail');
  L.push('- **Spice:** '+(m.spice!=null?m.spice:5)+'/10'+(flags.length?' — '+flags.join(', '):''));
  L.push('','---','');
  TRANSCRIPT.forEach(function(t){
    if(t.kind==='note') L.push('*'+t.text+'*','');
    else L.push('**'+t.name+':** '+t.text,'');
  });
  // 🔬 deep-dive protocol: the shared notebook is the run's real output — save it.
  if(m.protocol && DIRECTION){
    L.push('---','','## Shared notebook (final state)','');
    DIRECTION.split('\\n').forEach(function(x){ if(x.trim()) L.push('- '+x.trim()); });
    L.push('');
  }
  const blob=new Blob([L.join('\\n')],{type:'text/markdown'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  const slug=((m.topic||'conversation').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,40))||'conversation';
  const d=new Date(); const pad=function(n){ return (n<10?'0':'')+n; };
  a.download='duet-'+d.getFullYear()+pad(d.getMonth()+1)+pad(d.getDate())+'-'+pad(d.getHours())+pad(d.getMinutes())+'-'+slug+'.md';
  document.body.appendChild(a); a.click();
  setTimeout(function(){ try{ URL.revokeObjectURL(a.href); a.remove(); }catch(e){} }, 500);
}
saveBtn.addEventListener('click', saveTranscript);
document.getElementById('speakChk').addEventListener('change', primeAudio);
function refreshVoices(){ try{ window.speechSynthesis.getVoices(); }catch(e){} buildVoicePickers(); }
if('speechSynthesis' in window){
  try{ window.speechSynthesis.onvoiceschanged=refreshVoices; }catch(e){}
  refreshVoices();
  // iOS Safari often loads voices late and may never fire voiceschanged; poll
  // briefly until the lists actually fill, then stop (so it can't clobber a
  // selection the moment voices appear).
  let _vtries=0; const _vpoll=setInterval(function(){
    const sel=document.getElementById('voiceHexia');
    if((sel && sel.children.length>1) || ++_vtries>6){ clearInterval(_vpoll); return; }
    refreshVoices();
  }, 600);
} else { buildVoicePickers(); }
wireRatePickers();

/* The Web Serial Ohbot driver, the device gates (DRIVES_HEADS / WEBSERIAL_OK /
   LOCAL_DRIVERS) and the connect/disconnect/testNod/_reparkFor helpers now live
   in the shared /js/ohbot-heads.js (loaded above), so the duet, chat and
   calibration pages drive local USB-C heads identically. This page keeps only
   its own 2-head panel wiring below (swap is duet-only). */
async function swapHeads(){
  const a=LOCAL_DRIVERS.blue, b=LOCAL_DRIVERS.hexia;
  LOCAL_DRIVERS.blue=b; LOCAL_DRIVERS.hexia=a;
  // each physical head keeps its own calibration: reload for the role it now plays
  await _reparkFor('blue'); await _reparkFor('hexia');
  renderHeadPanel();
}
function renderHeadPanel(){
  [['blue','stBlueHead','nodBlue','discBlue','connBlue'],['hexia','stHexiaHead','nodHexia','discHexia','connHexia']].forEach(function(a){
    const on=!!LOCAL_DRIVERS[a[0]];
    const st=document.getElementById(a[1]); if(st) st.textContent=on?'connected \\u2713':'not connected';
    const nod=document.getElementById(a[2]); if(nod) nod.disabled=!on;
    const disc=document.getElementById(a[3]); if(disc) disc.disabled=!on;
    const conn=document.getElementById(a[4]); if(conn) conn.textContent=on?'Reconnect':'Connect';
  });
}
function setDevNote(html, show){ const dn=document.getElementById('devNote'); if(!dn) return; dn.innerHTML=html||''; dn.style.display=show?'block':'none'; }
function initLocalHeads(){
  // Let the shared connect helpers repaint THIS page's panel and route their
  // errors into the duet log.
  window.onLocalHeadsChanged = renderHeadPanel;
  window.onLocalHeadsNote = function(m){ addNote('('+m+')'); };
  if(DRIVES_HEADS) return;   // the PC drives the heads via the server, unchanged
  const panel=document.getElementById('usbHeads');
  if(WEBSERIAL_OK){
    if(panel) panel.style.display='flex';
    setDevNote("Heads plugged into <b>this device's</b> USB-C ports can move here \\u2014 connect each one below, then tap <b>Nod</b> to see which is which. (Otherwise you'll just hear the voices.)", true);
    const wire=function(id,fn){ const el=document.getElementById(id); if(el) el.addEventListener('click',fn); };
    wire('connBlue',function(){ connectHead('blue'); });
    wire('connHexia',function(){ connectHead('hexia'); });
    wire('nodBlue',function(){ testNod('blue'); });
    wire('nodHexia',function(){ testNod('hexia'); });
    wire('discBlue',function(){ disconnectHead('blue'); });
    wire('discHexia',function(){ disconnectHead('hexia'); });
    wire('swapHeads',swapHeads);
    renderHeadPanel();
  } else {
    const why=('serial' in navigator) ? "open this page at its <b>https</b> (Tailscale) address" : "use <b>Chrome or Edge</b>";
    setDevNote("On this device you'll just hear Blue and Hexia speak. To move heads plugged into this device, "+why+" and a USB connect panel will appear here.", true);
  }
}
initLocalHeads();
</script></body></html>"""
