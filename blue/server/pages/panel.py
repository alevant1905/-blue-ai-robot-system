"""Pure HTML template for the human-led three-robot Panel Mode page."""

PANEL_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Panel Mode — Blue, Hexia &amp; Casper</title>
<link rel="stylesheet" href="/assets/blue.css">
<script src="/assets/blue.js" defer></script>
<style>
:root{
  --bluec:#3da9fc;--hexiac:#b06cf0;--casperc:#f28c28;
  --cream:#faf8f4;--paper:#fff;--ink:#1a2e1a;--forest:#4a6b4a;
  --sage:#8fae8f;--slate:#64748b;--line:#cfc9bd;
  --green:#35b65a;--shadow:0 1px 3px rgba(0,0,0,.07)
}
*{box-sizing:border-box}
body{font-family:-apple-system,'Segoe UI',sans-serif;background:var(--cream);color:var(--ink);
  max-width:1060px;margin:0 auto;padding:28px 18px 110px;line-height:1.48}
h1{font-size:1.7em;margin:0 0 4px}.sub{color:var(--slate);margin:0 0 18px;max-width:850px}
.panel{background:var(--paper);border:1px solid var(--line);border-radius:15px;padding:16px;
  margin-bottom:15px;box-shadow:var(--shadow)}
.section-title{font-size:.75em;text-transform:uppercase;letter-spacing:.1em;color:var(--slate);
  font-weight:750;margin:0 0 9px}
.controls{display:flex;gap:9px;flex-wrap:wrap;align-items:center}
input[type=text],input[type=url],textarea{padding:10px 12px;border:1px solid var(--line);
  border-radius:9px;background:var(--paper);color:var(--ink);font:inherit}
input[type=text],input[type=url]{flex:1;min-width:250px}textarea{width:100%;resize:vertical;min-height:76px}
button{padding:9px 13px;border:1px solid var(--line);border-radius:9px;background:var(--paper);
  color:var(--ink);font:inherit;cursor:pointer}button:hover:not(:disabled){border-color:var(--sage)}
button.primary{background:#1a2e1a;color:#fff;border-color:#1a2e1a}button.mic.on,button.stop{background:#b42318;color:white;border-color:#b42318}
button:disabled{opacity:.46;cursor:default}.muted{color:var(--slate);font-size:.88em}.error{color:#c2413a!important}
.material-row{display:grid;grid-template-columns:1fr auto 1fr auto;gap:8px;align-items:center}
.material-row input[type=file]{max-width:100%;min-width:0;color:var(--slate)}
.chips{display:flex;gap:7px;flex-wrap:wrap;margin-top:9px}.chip{display:inline-flex;gap:6px;align-items:center;
  border-radius:999px;background:rgba(100,116,139,.1);padding:5px 9px;font-size:.82em}
.chip button{border:0;padding:0;background:transparent;color:var(--slate);font-size:1.15em;line-height:1}
.robot-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.robot{position:relative;border:1px solid var(--line);border-radius:14px;padding:13px;min-width:0;
  transition:border-color .16s,box-shadow .16s,transform .16s}
.robot.listening{border-color:var(--green);box-shadow:0 0 0 2px rgba(53,182,90,.18);transform:translateY(-1px)}
.robot-head{display:flex;align-items:center;gap:9px;margin-bottom:11px}.orb{width:13px;height:13px;border-radius:50%;background:var(--accent)}
.robot.listening .orb{background:var(--green);box-shadow:0 0 0 4px rgba(53,182,90,.14)}
.robot-name{font-weight:750}.robot-state{margin-left:auto;color:var(--slate);font-size:.76em}.robot.listening .robot-state{color:var(--green);font-weight:700}
.robot label{display:block;color:var(--slate);font-size:.76em;margin:8px 0 3px}.robot input[type=text]{width:100%;min-width:0;padding:8px 9px}
.docs summary{cursor:pointer;color:var(--slate);font-size:.78em;margin-top:9px}.doc-search{margin:6px 0!important}
.doc-list{max-height:170px;overflow:auto;border:1px solid rgba(100,116,139,.2);border-radius:8px;padding:6px}
.doc-list label{display:flex;gap:6px;align-items:flex-start;margin:0;padding:4px;font-size:.75em;color:var(--ink)}
.doc-list .folder{font-size:.68em;text-transform:uppercase;letter-spacing:.06em;color:var(--slate);padding:6px 4px 2px}
.local-head{margin-top:9px;font-size:.75em;padding:5px 8px;display:none}
.session-bar{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}
.pace{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-top:10px;
  padding-top:9px;border-top:1px solid rgba(100,116,139,.18)}
.pace input{flex:1;min-width:150px;max-width:320px}.pace .value{font-variant-numeric:tabular-nums}
#status{color:var(--slate);font-size:.9em;min-height:1.4em}.live-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#94a3b8;margin-right:6px}
.live-dot.on{background:var(--green);box-shadow:0 0 0 4px rgba(53,182,90,.12)}
#log{display:flex;flex-direction:column;gap:11px;margin:14px 0 18px;min-height:90px}
.turn{padding:11px 15px;border-radius:15px;max-width:80%;box-shadow:var(--shadow)}
.turn .who{font-size:.69em;text-transform:uppercase;letter-spacing:.09em;font-weight:750;margin-bottom:3px}
.turn.user{align-self:center;background:rgba(100,116,139,.1);border:1px solid rgba(100,116,139,.22);max-width:88%}.turn.user .who{color:var(--slate)}
.turn.blue{align-self:flex-start;background:#eaf4ff;border:1px solid #cfe4fb}.turn.blue .who{color:var(--bluec)}
.turn.hexia{align-self:flex-end;background:#f4ecfc;border:1px solid #e6d6f7}.turn.hexia .who{color:var(--hexiac)}
.turn.pico{align-self:center;background:#fff2e4;border:1px solid #f5d2ad}.turn.pico .who{color:var(--casperc)}
.turn.speaking{box-shadow:0 0 0 2px currentColor,var(--shadow)}
.note{align-self:center;color:var(--slate);font-size:.82em;text-align:center;padding:4px 10px;border-radius:999px;background:rgba(100,116,139,.08)}
.composer{position:sticky;bottom:10px;z-index:3;background:color-mix(in srgb,var(--paper) 94%,transparent);backdrop-filter:blur(14px)}
.composer-actions{display:flex;gap:8px;margin-top:8px;align-items:center;flex-wrap:wrap}.composer-actions .hint{margin-left:auto}
:root:not([data-theme="light"]) .turn.blue{background:rgba(61,169,252,.12);border-color:rgba(61,169,252,.35)}
:root:not([data-theme="light"]) .turn.hexia{background:rgba(176,108,240,.12);border-color:rgba(176,108,240,.35)}
:root:not([data-theme="light"]) .turn.pico{background:rgba(242,140,40,.12);border-color:rgba(242,140,40,.35)}
@media(max-width:820px){.robot-grid{grid-template-columns:1fr}.material-row{grid-template-columns:1fr auto}.turn{max-width:93%}}
@media(max-width:520px){body{padding-left:12px;padding-right:12px}.material-row{grid-template-columns:1fr}.material-row button{width:100%}.composer-actions .hint{width:100%;margin-left:0}}
</style>
</head>
<body>
<h1>Panel Mode</h1>
<p class="sub">Speak naturally with Blue, Hexia, and Casper in one room. Call a robot’s name to give them the floor; they answer once, then the floor returns to the room — say a name again for the next question. Say a name on its own and that robot waits for what you say next. Mentioning another robot inside the question does not switch speakers. Every robot still hears the full conversation. Turn on <strong>continuous</strong> and they discuss the topic with each other in a random order, without waiting to be asked — say something at any time and they take it up.</p>

<section class="panel">
  <div class="section-title">Discussion</div>
  <div class="controls">
    <input id="topic" type="text" maxlength="700" placeholder="Discussion topic — optional for an open conversation">
  </div>
  <div class="material-row" style="margin-top:10px">
    <input id="websiteUrl" type="url" maxlength="1200" placeholder="https://example.com/article">
    <button id="addWebsite">Add website</button>
    <input id="pdfFile" type="file" accept="application/pdf,.pdf">
    <button id="addPdf">Add PDF</button>
  </div>
  <div id="materials" class="chips" aria-live="polite"></div>
  <div id="materialStatus" class="muted" style="margin-top:7px">Websites and PDFs are read once, then shared with the whole panel.</div>
</section>

<section class="panel">
  <div class="section-title">Who they are in this discussion</div>
  <div class="robot-grid">
    <article class="robot" id="robot-blue" style="--accent:var(--bluec)">
      <div class="robot-head"><span class="orb"></span><span class="robot-name">Blue</span><span class="robot-state">waiting</span></div>
      <label for="role-blue">Role / perspective</label><input id="role-blue" type="text" maxlength="500" placeholder="e.g. careful systems thinker">
      <label for="slang-blue">Slang / register</label><input id="slang-blue" type="text" maxlength="350" placeholder="e.g. plain Canadian English">
      <details class="docs"><summary><span id="count-blue">0</span> library documents selected</summary><input class="doc-search" data-robot="blue" type="text" placeholder="Filter library"><div class="doc-list" id="docs-blue"></div></details>
      <button class="local-head" data-connect="blue">Connect local head</button>
    </article>
    <article class="robot" id="robot-hexia" style="--accent:var(--hexiac)">
      <div class="robot-head"><span class="orb"></span><span class="robot-name">Hexia</span><span class="robot-state">waiting</span></div>
      <label for="role-hexia">Role / perspective</label><input id="role-hexia" type="text" maxlength="500" placeholder="e.g. skeptical cultural critic">
      <label for="slang-hexia">Slang / register</label><input id="slang-hexia" type="text" maxlength="350" placeholder="e.g. dry Gen X wit">
      <details class="docs"><summary><span id="count-hexia">0</span> library documents selected</summary><input class="doc-search" data-robot="hexia" type="text" placeholder="Filter library"><div class="doc-list" id="docs-hexia"></div></details>
      <button class="local-head" data-connect="hexia">Connect local head</button>
    </article>
    <article class="robot" id="robot-pico" style="--accent:var(--casperc)">
      <div class="robot-head"><span class="orb"></span><span class="robot-name">Casper</span><span class="robot-state">waiting</span></div>
      <label for="role-pico">Role / perspective</label><input id="role-pico" type="text" maxlength="500" placeholder="e.g. practical newcomer">
      <label for="slang-pico">Slang / register</label><input id="slang-pico" type="text" maxlength="350" placeholder="e.g. light Gen Z slang">
      <details class="docs"><summary><span id="count-pico">0</span> library documents selected</summary><input class="doc-search" data-robot="pico" type="text" placeholder="Filter library"><div class="doc-list" id="docs-pico"></div></details>
      <button class="local-head" data-connect="pico">Connect local head</button>
    </article>
  </div>
</section>

<section class="panel">
  <div class="session-bar">
    <div id="status"><span class="live-dot" id="liveDot"></span>Panel is ready.</div>
    <div class="controls">
      <button class="primary" id="startBtn">Start panel</button>
      <button class="stop" id="interruptBtn" disabled>Stop talking</button>
      <button id="stopBtn" disabled>End panel</button>
      <button id="saveBtn" disabled>Save transcript</button>
      <label class="muted"><input id="continuousChk" type="checkbox"> continuous discussion</label>
      <label class="muted"><input id="speakChk" type="checkbox" checked> speak replies aloud</label>
    </div>
  </div>
  <label class="pace muted" for="paceRange">Pause between turns
    <input id="paceRange" type="range" min="0" max="8" step="0.1" value="1.1">
    <span class="value" id="paceLabel">1.1 s · natural</span>
  </label>
</section>

<main id="log" aria-live="polite"><div class="note">Start the panel, then say “Blue…”, “Hexia…”, “Casper…”, or “everyone…”. Or tick continuous and let them talk it out.</div></main>

<section class="panel composer">
  <textarea id="messageInput" maxlength="1600" placeholder="Call a robot by name, then ask your question…"></textarea>
  <div class="composer-actions">
    <button class="mic" id="micBtn">Start listening</button>
    <button class="primary" id="sendBtn">Send</button>
    <span class="muted" id="micStatus">Voice recognition uses this device’s browser.</span>
    <span class="muted hint">Ctrl/⌘ + Enter to send</span>
  </div>
</section>

<audio id="panelAudio" preload="auto"></audio>
<script src="/js/ohbot-heads.js"></script>
<script>
const ROBOTS={{ robots_json|safe }};
const DOCS={{ documents_json|safe }};
const IDS=['blue','hexia','pico'];
const DRIVES_SERVER_HEADS=(typeof blueDeviceTag==='function')?(blueDeviceTag()==='windows'):true;
const logEl=document.getElementById('log'),statusEl=document.getElementById('status');
const startBtn=document.getElementById('startBtn'),stopBtn=document.getElementById('stopBtn');
const interruptBtn=document.getElementById('interruptBtn'),saveBtn=document.getElementById('saveBtn'),sendBtn=document.getElementById('sendBtn');
const micBtn=document.getElementById('micBtn'),inputEl=document.getElementById('messageInput');
const audioEl=document.getElementById('panelAudio'),continuousChk=document.getElementById('continuousChk');
const paceRange=document.getElementById('paceRange'),paceLabel=document.getElementById('paceLabel');
// The floor is a LIST, not one name: "everyone" hands it to all three at once.
let running=false,busy=false,activeRobots=[],history=[],materials=[];
// Continuous discussion: a random running order the loop walks through, and the
// last robot who actually spoke, so the seam between two lineups (or between an
// answer to Alex and the next free turn) never hands anyone two turns in a row.
let loopActive=false,lineup=[],lineupIndex=0,lastRobotTurn='',continuousFailures=0;
let recognition=null,listening=false,resumeListening=false,activeFinish=null,audioUrl='',audioAbort=null,turnAbort=null,turnVersion=0;
let lastRobotSpeech='',echoGuardUntil=0,recognitionRestartAfter=0;
const voicePrefs={{ voice_preferences_json|safe }};

function setStatus(text,error){statusEl.innerHTML='<span class="live-dot '+(running?'on':'')+'"></span>'+escapeHtml(text||'');statusEl.className=error?'error':'';}
function escapeHtml(text){return String(text||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function addNote(text){const el=document.createElement('div');el.className='note';el.textContent=text;logEl.appendChild(el);scrollDown();}
function addTurn(speaker,text){
  const cfg=speaker==='user'?{name:'Alex',id:'user'}:ROBOTS[speaker];
  const el=document.createElement('div');el.className='turn '+cfg.id;
  const who=document.createElement('div');who.className='who';who.textContent=cfg.name;
  const body=document.createElement('div');body.textContent=text;el.appendChild(who);el.appendChild(body);logEl.appendChild(el);
  history.push({speaker:speaker,text:text});if(speaker!=='user')lastRobotTurn=speaker;saveBtn.disabled=false;scrollDown();return el;
}
function scrollDown(){requestAnimationFrame(()=>window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'}));}
function sleep(ms){return new Promise(resolve=>setTimeout(resolve,ms));}
function continuousOn(){return !!continuousChk.checked;}
// Read live, never captured: dragging the slider mid-discussion changes the very
// next pause rather than the next time the panel is started.
function paceMs(){const seconds=parseFloat(paceRange.value);return isNaN(seconds)?1100:Math.round(seconds*1000);}
function paceWord(seconds){seconds=+seconds;return seconds<=0.2?'straight on':seconds<=1.5?'natural':seconds<=3?'unhurried':seconds<=5.5?'slow':'long pauses';}
function renderPace(){paceLabel.textContent=(+paceRange.value).toFixed(1)+' s · '+paceWord(paceRange.value);}
paceRange.addEventListener('input',renderPace);
paceRange.addEventListener('change',saveSettings);
// The gap is waited out in slices so a change to the slider — or Alex taking
// the floor — is felt at once instead of after a pause he has already changed.
async function pauseBetweenTurns(){
  const started=Date.now();
  while(running&&continuousOn()&&!busy){
    const remaining=paceMs()-(Date.now()-started);
    if(remaining<=0)return;
    await sleep(Math.min(200,remaining));
  }
}
// Accepts a name, a list of names, or nothing at all.
function setActive(robot,label){
  const list=Array.isArray(robot)?robot.slice():(robot?[robot]:[]);
  activeRobots=list.filter(id=>IDS.indexOf(id)>=0);
  IDS.forEach(id=>{const card=document.getElementById('robot-'+id),state=card.querySelector('.robot-state'),
    holding=activeRobots.indexOf(id)>=0;
    card.classList.toggle('listening',holding);state.textContent=holding?(label||'listening'):'hearing all';});
}
// Highlight a continuous speaker WITHOUT giving them the floor: nobody is being
// addressed in continuous mode, so activeRobots must stay as Alex left it.
function showSpeaking(id){
  IDS.forEach(key=>{const card=document.getElementById('robot-'+key),state=card.querySelector('.robot-state'),on=key===id;
    card.classList.toggle('listening',on);state.textContent=on?'speaking':'hearing all';});
}
function selectedSettings(){
  const out={};IDS.forEach(id=>{out[id]={role:document.getElementById('role-'+id).value.trim(),slang:document.getElementById('slang-'+id).value.trim(),documents:Array.from(document.querySelectorAll('#docs-'+id+' input[type=checkbox]:checked')).map(x=>x.value)};});return out;
}
function saveSettings(){
  try{localStorage.setItem('bluePanelSettings',JSON.stringify({topic:document.getElementById('topic').value,continuous:continuousOn(),pace:parseFloat(paceRange.value),robots:selectedSettings()}));}catch(e){}
}
function restoreSettings(){
  let data={};try{data=JSON.parse(localStorage.getItem('bluePanelSettings')||'{}')||{};}catch(e){}
  if(typeof data.topic==='string')document.getElementById('topic').value=data.topic;
  continuousChk.checked=!!data.continuous;
  if(typeof data.pace==='number'&&isFinite(data.pace))paceRange.value=Math.min(8,Math.max(0,data.pace));
  renderPace();
  IDS.forEach(id=>{const cfg=(data.robots||{})[id]||{};if(typeof cfg.role==='string')document.getElementById('role-'+id).value=cfg.role;if(typeof cfg.slang==='string')document.getElementById('slang-'+id).value=cfg.slang;});
  return data.robots||{};
}
function buildDocumentPickers(saved){
  IDS.forEach(id=>{
    const box=document.getElementById('docs-'+id);let folder='';
    DOCS.forEach(doc=>{const f=doc.folder||'Library';if(f!==folder){folder=f;const h=document.createElement('div');h.className='folder';h.textContent=f;box.appendChild(h);}
      const lab=document.createElement('label'),cb=document.createElement('input'),sp=document.createElement('span');cb.type='checkbox';cb.value=doc.filename;cb.checked=((saved[id]||{}).documents||[]).includes(doc.filename);sp.textContent=doc.filename;lab.appendChild(cb);lab.appendChild(sp);box.appendChild(lab);});
    const update=()=>{document.getElementById('count-'+id).textContent=box.querySelectorAll('input:checked').length;saveSettings();};box.addEventListener('change',update);update();
  });
  document.querySelectorAll('.doc-search').forEach(input=>input.addEventListener('input',()=>{const q=input.value.trim().toLowerCase();document.querySelectorAll('#docs-'+input.dataset.robot+' label').forEach(l=>l.hidden=!!q&&!l.textContent.toLowerCase().includes(q));}));
}
const savedSettings=restoreSettings();buildDocumentPickers(savedSettings);
document.getElementById('topic').addEventListener('change',saveSettings);IDS.forEach(id=>['role-','slang-'].forEach(prefix=>document.getElementById(prefix+id).addEventListener('change',saveSettings)));

function renderMaterials(){
  const box=document.getElementById('materials');box.innerHTML='';materials.forEach((source,index)=>{const chip=document.createElement('span');chip.className='chip';chip.appendChild(document.createTextNode((source.kind==='pdf'?'PDF · ':'Web · ')+source.label));const x=document.createElement('button');x.type='button';x.setAttribute('aria-label','Remove '+source.label);x.textContent='×';x.onclick=()=>{materials.splice(index,1);renderMaterials();};chip.appendChild(x);box.appendChild(chip);});
}
async function addSource(kind){
  if(materials.length>=4){setMaterialStatus('Panel Mode accepts up to four shared materials.',true);return;}
  const form=new FormData();form.append('kind',kind);
  if(kind==='website'){const url=document.getElementById('websiteUrl').value.trim();if(!url){setMaterialStatus('Paste a website address first.',true);return;}form.append('url',url);}else{const file=document.getElementById('pdfFile').files[0];if(!file){setMaterialStatus('Choose a PDF first.',true);return;}form.append('file',file);}
  setMaterialStatus(kind==='website'?'Reading website…':'Reading PDF…');
  try{const response=await fetch('/panel/source',{method:'POST',body:form}),data=await response.json();if(!response.ok||!data.ok)throw new Error(data.error||'Source could not be prepared.');materials.push(data.source);renderMaterials();setMaterialStatus('Ready: '+data.source.label+' · '+Number(data.sourceCharacters||0).toLocaleString()+' readable characters');}
  catch(error){setMaterialStatus(error.message||'Source could not be prepared.',true);}
}
function setMaterialStatus(text,error){const el=document.getElementById('materialStatus');el.textContent=text;el.className=error?'muted error':'muted';}
document.getElementById('addWebsite').onclick=()=>addSource('website');document.getElementById('addPdf').onclick=()=>addSource('pdf');

function localCall(name,args){try{return typeof window[name]==='function'&&window[name].apply(window,args);}catch(e){return false;}}
async function acknowledge(id){
  setActive(id);const cfg=ROBOTS[id],green={r:0,g:10,b:0};
  if(id==='blue'||id==='pico')localCall('localHeadControl',[cfg.head,'/head/eye-color',green]);
  const localNod=localCall('localHeadControl',[cfg.head,'/head/action',{action:'nod_yes',times:1}]);
  const localColor=(id==='hexia')?true:!!(typeof LOCAL_DRIVERS!=='undefined'&&LOCAL_DRIVERS[cfg.head]);
  if(localNod&&localColor)return;
  if(!DRIVES_SERVER_HEADS)return;
  try{await fetch('/panel/ack',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({robot:id})});}catch(e){}
}
function cleanSpeech(text){return String(text||'').replace(/[*_`#]/g,'').replace(/\s+/g,' ').trim();}
function normalizedSpeech(text){return String(text||'').toLowerCase().replace(/[^a-z0-9\s]/g,' ').replace(/\s+/g,' ').trim();}
function armRobotEcho(text){lastRobotSpeech=normalizedSpeech(text);echoGuardUntil=Date.now()+60000;}
function isLikelyRobotEcho(text){
  if(!lastRobotSpeech||Date.now()>echoGuardUntil)return false;
  const heard=normalizedSpeech(text);if(heard.length<4)return false;
  if(/^(?:blue|hexia|casper|everyone|everybody)$/.test(heard))return false;
  if(lastRobotSpeech.includes(heard)||heard.includes(lastRobotSpeech))return true;
  const words=heard.split(' ').filter(Boolean);if(words.length<5)return false;
  const spokenWords=new Set(lastRobotSpeech.split(' ').filter(Boolean));
  const overlap=words.filter(word=>spokenWords.has(word)).length;
  const hasDistinctiveWord=words.some(word=>word.length>=6&&spokenWords.has(word));
  return hasDistinctiveWord&&overlap/words.length>=.8;
}
function flushRecognitionAfterSpeech(){
  echoGuardUntil=Date.now()+4000;recognitionRestartAfter=Date.now()+700;
  if(recognition&&listening&&resumeListening){try{recognition.abort();}catch(e){}}
}
function voiceRate(id){let saved='';try{saved=localStorage.getItem('blueVoiceRate_'+id)||'';}catch(e){}const n=parseFloat(saved);return saved&&!isNaN(n)?n:((ROBOTS[id]&&ROBOTS[id].voiceRate)||1);}
function browserVoices(){return ((window.speechSynthesis&&window.speechSynthesis.getVoices())||[]).filter(v=>/^(en|fr|ru|el|da)/i.test(v.lang||''));}
function preferredBrowserVoiceName(id){let name=(voicePrefs[id]&&voicePrefs[id].provider==='browser'&&voicePrefs[id].voice)||'';if(!name){try{name=localStorage.getItem('blueVoiceName_'+id)||'';}catch(e){}}return name;}
function waitForBrowserVoice(id,timeoutMs){
  const ready=()=>{const voices=browserVoices(),name=preferredBrowserVoiceName(id);return name?voices.some(v=>v.name===name):voices.length>0;};
  if(ready())return Promise.resolve(true);
  return new Promise(resolve=>{const started=Date.now(),timer=setInterval(()=>{if(ready()||Date.now()-started>=(timeoutMs||3500)){clearInterval(timer);resolve(ready());}},100);});
}
function pickedBrowserVoice(id){const name=preferredBrowserVoiceName(id),voices=browserVoices();if(name){const found=voices.find(v=>v.name===name);if(found)return found;}const cfg=ROBOTS[id]||{},wanted=cfg.preferFemale?['Samantha','Victoria','Karen','Microsoft Zira']:['Daniel','Aaron','Arthur','Microsoft David'];for(const x of wanted){const found=voices.find(v=>v.name===x||v.name.indexOf(x)===0);if(found)return found;}return voices.find(v=>/^en/i.test(v.lang||''))||voices[0]||null;}
function lipFrames(text,rate){const words=(text.match(/[^\s]+/g)||[]),frames=[],scale=1/(rate||1);words.forEach(word=>{const core=word.replace(/[^A-Za-z0-9\u00C0-\u024F]/g,''),duration=Math.min(.72,Math.max(.14,Math.max(1,core.length)*.058))*scale,moves=Math.max(1,Math.round(Math.max(1,core.length)/3)),per=duration/moves;for(let i=0;i<moves;i++){frames.push([.58+Math.random()*.4,per*.62]);frames.push([.08,per*.38]);}frames.push([0,(/[.!?]/.test(word.slice(-1))?.38:/[,;:]/.test(word.slice(-1))?.2:.055)*scale]);});return frames;}
function headLip(cfg,frames){if(localCall('localHeadLip',[cfg.head,frames]))return;if(!DRIVES_SERVER_HEADS)return;fetch('/head/'+cfg.head+'/lip-seq',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({frames:frames})}).catch(()=>{});}
function headLipStop(cfg){if(localCall('localHeadLipStop',[cfg.head]))return;if(!DRIVES_SERVER_HEADS)return;fetch('/head/'+cfg.head+'/lip',{method:'POST',headers:{'Content-Type':'application/json'},body:'{"on":false}'}).catch(()=>{});}
function headMood(cfg,mood){if(!mood)return;const body={r:mood.r|0,g:mood.g|0,b:mood.b|0,name:mood.name||'neutral',expression:mood.expression||mood.name||'neutral'};if(localCall('localHeadControl',[cfg.head,'/head/eye-color',body]))return;if(!DRIVES_SERVER_HEADS)return;fetch('/head/'+cfg.head+(cfg.headDriver==='picoh'?'/mood':'/eye-color'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).catch(()=>{});}
function stopAudio(){try{window.speechSynthesis.cancel();}catch(e){}if(audioAbort){try{audioAbort.abort();}catch(e){}audioAbort=null;}try{audioEl.pause();audioEl.removeAttribute('src');audioEl.load();}catch(e){}if(audioUrl){try{URL.revokeObjectURL(audioUrl);}catch(e){}audioUrl='';}}
async function speakAs(cfg,text,el,mood,turnToken){
  const initialPref=voicePrefs[cfg.id]||{};
  if(initialPref.provider==='browser')await waitForBrowserVoice(cfg.id,3500);
  if(turnToken!==turnVersion)return;
  return new Promise(resolve=>{
    const spoken=cleanSpeech(text),rate=voiceRate(cfg.id),frames=lipFrames(spoken,rate);
    const speechWasEnabled=document.getElementById('speakChk').checked;
    let done=false,started=false,keepAlive=null;
    if(speechWasEnabled)armRobotEcho(spoken);
    const embody=()=>{if(started)return;started=true;el.classList.add('speaking');headLip(cfg,frames);headMood(cfg,mood);};
    const finish=()=>{if(done)return;done=true;if(activeFinish===finish)activeFinish=null;if(keepAlive)clearInterval(keepAlive);stopAudio();if(started){headLipStop(cfg);el.classList.remove('speaking');}if(speechWasEnabled)flushRecognitionAfterSpeech();resolve();};
    activeFinish=finish;
    if(!speechWasEnabled){embody();setTimeout(finish,700);return;}
    const browserSpeak=()=>{if(done||turnToken!==turnVersion)return;embody();try{const u=new SpeechSynthesisUtterance(spoken),v=pickedBrowserVoice(cfg.id);if(v){u.voice=v;u.lang=v.lang||'en-US';}u.rate=rate;u.pitch=cfg.voicePitch||1;u.onend=finish;u.onerror=finish;window.speechSynthesis.speak(u);keepAlive=setInterval(()=>{try{if(window.speechSynthesis.speaking){window.speechSynthesis.pause();window.speechSynthesis.resume();}}catch(e){}},9000);}catch(e){finish();}};
    const pref=voicePrefs[cfg.id]||{};
    if(pref.provider==='edge'&&pref.voice){audioAbort=typeof AbortController!=='undefined'?new AbortController():null;const options={method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:spoken,voice:pref.voice,rate:rate,pitch:cfg.voicePitch||1})};if(audioAbort)options.signal=audioAbort.signal;fetch('/tts/synthesize',options).then(r=>{if(!r.ok)throw new Error();return r.blob();}).then(blob=>{if(done||turnToken!==turnVersion)return;audioUrl=URL.createObjectURL(blob);audioEl.src=audioUrl;audioEl.onended=finish;audioEl.onerror=finish;embody();return audioEl.play();}).catch(e=>{if(!done&&(!e||e.name!=='AbortError'))browserSpeak();});}else browserSpeak();
    setTimeout(finish,45000);
  });
}
Promise.all(IDS.map(id=>fetch('/tts/preferences/'+id).then(r=>r.json()).catch(()=>null))).then(values=>values.forEach((value,index)=>{if(value&&value.ok)voicePrefs[IDS[index]]={provider:value.provider||'browser',voice:value.voice||''};}));

function localRoutingFallback(text){
  const value=String(text||'').trim(),lower=value.toLowerCase();let explicit=[];
  if(/^(?:(?:hey|hi|hello|okay|ok|yo|please)\b[\s,!:;\-—]*)*(?:everyone|everybody|all\s+three|all\s+of\s+you)\b/i.test(value)||/(?:[,;:—-]\s*)(?:everyone|everybody|all\s+three|all\s+of\s+you)\s*[?!.]*$/i.test(value))explicit=IDS.slice();
  if(!explicit.length){const lead=value.match(/^(?:(?:hey|hi|hello|okay|ok|yo|please)\b[\s,!:;\-—]*)*(blue|hexia|casper|caspar|pico|picoh)(?=\s*[,!:;—-]|\s*$|\s+(?:what|who|how|why|when|where|do|does|did|can|could|would|will|tell|give|explain|respond|your|i)\b)/i);if(lead)explicit=[/^(casper|caspar|pico|picoh)$/i.test(lead[1])?'pico':lead[1].toLowerCase()];}
  if(!explicit.length){const trail=value.match(/(?:[,;:—-]\s*|\b(?:what\s+do\s+you\s+think|your\s+take|over\s+to\s+you)\s+)(blue|hexia|casper|caspar|pico|picoh)\s*[?!.]*$/i);if(trail)explicit=[/^(casper|caspar|pico|picoh)$/i.test(trail[1])?'pico':trail[1].toLowerCase()];}
  let residual=lower.replace(/\ball\s+of\s+you\b|\ball\s+three\b/g,' ').replace(/\b(?:hey|hi|hello|okay|ok|yo|please|and|everyone|everybody|blue|hexia|casper|caspar|pico|picoh)\b/g,' ').replace(/[^a-z0-9]+/g,' ').trim();
  return {targets:explicit.length?explicit:activeRobots.slice(),explicit:!!explicit.length,nameOnly:!!explicit.length&&!residual};
}
async function resolveRouting(text){
  try{const response=await fetch('/panel/route',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:text,activeRobot:activeRobots})}),data=await response.json();if(response.ok&&data.ok&&Array.isArray(data.targets))return data;}catch(e){}
  return localRoutingFallback(text);
}
function isStopCommand(raw){
  const text=String(raw||'').toLowerCase().replace(/[^a-z\s]/g,' ').replace(/\s+/g,' ').trim();
  return /^(?:(?:please|robots?|blue|hexia|casper)\s+)*(?:stop|stop talking|stop speaking|be quiet|quiet|enough|cancel)(?:\s+(?:now|please|talking|speaking))?$/.test(text);
}
function interruptReply(message,keepGoing){
  turnVersion+=1;
  if(turnAbort){try{turnAbort.abort();}catch(e){}turnAbort=null;}
  if(activeFinish)activeFinish();else stopAudio();
  busy=false;sendBtn.disabled=false;interruptBtn.disabled=true;
  // Cut off mid-answer is still an answer that ended: the floor goes back to
  // the room rather than staying with whoever was talking.
  setActive('');
  // "Stop talking" has to stop the discussion as well. A continuous panel that
  // resumed a second later would simply be ignoring him. `keepGoing` is for the
  // one case that is not a stop: Alex barging in on a turn to say his piece.
  if(!keepGoing&&continuousOn()){
    continuousChk.checked=false;saveSettings();
    if(message!==false)message=message||'Discussion paused. Tick “continuous” when you want them talking again.';
  }
  if(message!==false)setStatus(message||'Stopped. Panel is listening. Call a robot by name.');
  if(resumeListening&&running&&!listening)setTimeout(startRecognition,50);
}
// A random running order, refilled from the server so the weighting that keeps
// nobody twice in a row and nobody starved lives in one place.
async function refillLineup(){
  const avoid=lastRobotTurn;
  try{
    const response=await fetch('/panel/lineup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({turns:9,avoid:avoid})}),data=await response.json();
    if(response.ok&&data.ok&&Array.isArray(data.lineup)&&data.lineup.length){lineup=data.lineup;lineupIndex=0;return;}
  }catch(e){}
  const out=[];let previous=avoid;
  for(let i=0;i<9;i++){const options=IDS.filter(id=>id!==previous);previous=options[Math.floor(Math.random()*options.length)];out.push(previous);}
  lineup=out;lineupIndex=0;
}
async function nextSpeaker(){
  if(lineupIndex>=lineup.length)await refillLineup();
  let id=lineup[lineupIndex++];
  if(id===lastRobotTurn&&lineupIndex<lineup.length)id=lineup[lineupIndex++];
  return id;
}
async function runContinuous(){
  if(loopActive)return;loopActive=true;continuousFailures=0;
  try{
    while(running&&continuousOn()){
      // Alex's own turn owns the floor while it runs; wait it out rather than
      // talking over him.
      if(busy){await sleep(180);continue;}
      const topic=document.getElementById('topic').value.trim();
      if(!topic&&!history.length){setStatus('Give them a topic, or say something, and they will take it from there.');await sleep(700);continue;}
      const id=await nextSpeaker();if(!running||!continuousOn()||busy)continue;
      const cfg=ROBOTS[id],thisTurn=++turnVersion;
      busy=true;interruptBtn.disabled=false;showSpeaking(id);setStatus(cfg.name+' is thinking…');
      try{
        turnAbort=typeof AbortController!=='undefined'?new AbortController():null;
        const options={method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({speaker:id,mode:'continuous',text:'',topic:topic,history:history,settings:selectedSettings(),materials:materials})};
        if(turnAbort)options.signal=turnAbort.signal;
        const response=await fetch('/panel/turn',options);turnAbort=null;
        const data=await response.json().catch(()=>null);
        if(thisTurn!==turnVersion||!running)continue;
        if(!response.ok||!data||!data.ok)throw new Error((data&&data.error)||'that turn could not be generated');
        continuousFailures=0;
        const el=addTurn(id,data.text);setStatus(cfg.name+' is speaking…');
        await speakAs(cfg,data.text,el,data.eye_mood,thisTurn);
      }catch(error){
        if((error&&error.name==='AbortError')||thisTurn!==turnVersion)continue;
        continuousFailures+=1;
        addNote(cfg.name+' could not take a turn: '+((error&&error.message)||'unknown error'));
        if(continuousFailures>=3){continuousChk.checked=false;saveSettings();setStatus('The discussion stopped: the robots could not keep answering.',true);}
        else await sleep(1500);
      }finally{
        if(thisTurn===turnVersion){busy=false;turnAbort=null;interruptBtn.disabled=true;setActive(activeRobots);}
      }
      await pauseBetweenTurns();
    }
  }finally{loopActive=false;}
}
function setContinuous(on){
  continuousChk.checked=!!on;saveSettings();
  if(!continuousChk.checked){setStatus('Continuous discussion off. Call a robot by name.');return;}
  if(!running)startPanel();
  setStatus('They will discuss it on their own — say something whenever you want to join in.');
  runContinuous();
}
continuousChk.onchange=()=>setContinuous(continuousChk.checked);
async function submitUtterance(raw){
  const text=String(raw||'').replace(/\s+/g,' ').trim();if(!text)return;if(isStopCommand(text)){interruptReply();return;}
  // In a continuous discussion Alex would otherwise never get a word in: a
  // robot is nearly always mid-turn, so his line cuts that turn short instead
  // of being dropped. The discussion itself keeps running.
  if(busy){if(!continuousOn())return;interruptReply(false,true);}
  if(!running)startPanel();
  const thisTurn=++turnVersion;inputEl.value='';busy=true;sendBtn.disabled=true;interruptBtn.disabled=false;
  // Set only when a bare name was called and nobody answered yet — that is the
  // one case where the floor survives into the next utterance.
  let heldForFollowUp=false;
  try{
    const routing=await resolveRouting(text),targets=routing.targets||[];addTurn('user',text);
    if(thisTurn!==turnVersion)return;
    // Unaddressed, the remark reaches nobody — unless the discussion is running
    // on its own, in which case it is simply the next thing said in the room and
    // whoever speaks next answers it.
    if(!targets.length){setStatus(continuousOn()?'Heard. They will pick it up.':'Everyone heard that. Call Blue, Hexia, or Casper by name to choose who answers.',!continuousOn());return;}
    for(const id of targets){if(thisTurn!==turnVersion||!running)return;await acknowledge(id);if(thisTurn!==turnVersion||!running)return;if(routing.nameOnly)continue;setStatus(ROBOTS[id].name+' is thinking…');
      turnAbort=typeof AbortController!=='undefined'?new AbortController():null;const options={method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({speaker:id,text:text,topic:document.getElementById('topic').value.trim(),history:history,settings:selectedSettings(),materials:materials})};if(turnAbort)options.signal=turnAbort.signal;
      const response=await fetch('/panel/turn',options);turnAbort=null;
      if(thisTurn!==turnVersion||!running)return;
      const data=await response.json();if(!response.ok||!data.ok){addNote(ROBOTS[id].name+' could not answer: '+(data.error||'unknown error'));continue;}
      const el=addTurn(id,data.text);await speakAs(ROBOTS[id],data.text,el,data.eye_mood,thisTurn);
    }
    // The floor lasts one answer. A robot that has finished replying goes back
    // to hearing-all, so the next thing said reaches nobody until Alex names
    // someone again — otherwise the last speaker quietly keeps answering
    // everything, including remarks meant for the room.
    // The exception is a bare name: "Hexia" with no question IS the act of
    // addressing her, so she holds the floor for the sentence that follows.
    if(thisTurn===turnVersion){
      // setActive(targets), not whatever the acknowledgement loop left behind:
      // it lights each robot in turn, so "everyone" used to end with only
      // Casper holding the floor and answering the next question alone.
      if(routing.nameOnly){heldForFollowUp=true;setActive(targets);setStatus(targets.map(id=>ROBOTS[id].name).join(', ')+' listening.');}
      else setStatus(continuousOn()?'Back to the discussion…':'Panel is listening. Call a robot by name.');
    }
  }catch(error){if(error&&error.name!=='AbortError'&&thisTurn===turnVersion)setStatus(error.message||'Panel turn failed.',true);}finally{if(thisTurn===turnVersion){if(!heldForFollowUp)setActive('');turnAbort=null;busy=false;sendBtn.disabled=false;interruptBtn.disabled=true;if(resumeListening&&running&&!listening)startRecognition();}}
}
function startPanel(){running=true;startBtn.disabled=true;stopBtn.disabled=false;saveSettings();
  if(continuousOn()){setStatus('They will discuss it on their own — say something whenever you want to join in.');runContinuous();}
  else setStatus('Panel is listening. Call a robot by name.');}
function stopPanel(){running=false;interruptReply(false);startBtn.disabled=false;stopBtn.disabled=true;setActive('');stopRecognition(false);setStatus('Panel ended. The transcript is still available.');}
startBtn.onclick=startPanel;interruptBtn.onclick=()=>interruptReply();stopBtn.onclick=stopPanel;sendBtn.onclick=()=>submitUtterance(inputEl.value);inputEl.addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();submitUtterance(inputEl.value);}});

function setupRecognition(){
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;if(!SR){micBtn.disabled=true;document.getElementById('micStatus').textContent='Voice recognition is not available in this browser; use the text box.';return;}
  recognition=new SR();recognition.continuous=true;recognition.interimResults=true;recognition.lang='en-CA';
  recognition.onstart=()=>{listening=true;micBtn.classList.add('on');micBtn.textContent='Stop listening';document.getElementById('micStatus').textContent='Listening for a robot name…';};
  recognition.onresult=event=>{let finalText='',interim='';for(let i=event.resultIndex;i<event.results.length;i++){const t=event.results[i][0].transcript;if(event.results[i].isFinal)finalText+=t;else interim+=t;}const heard=(finalText||interim).trim();if(heard&&isStopCommand(heard)){interruptReply();return;}if(heard&&isLikelyRobotEcho(heard)){document.getElementById('micStatus').textContent='Ignoring robot audio…';return;}if(interim&&!busy)document.getElementById('micStatus').textContent='Hearing: '+interim;if(finalText&&!busy)submitUtterance(finalText);};
  recognition.onerror=event=>{if(event.error!=='aborted'&&event.error!=='no-speech')document.getElementById('micStatus').textContent='Microphone: '+event.error;};
  recognition.onend=()=>{listening=false;micBtn.classList.remove('on');micBtn.textContent='Start listening';if(resumeListening&&running)setTimeout(startRecognition,Math.max(250,recognitionRestartAfter-Date.now()));};
}
function startRecognition(){if(!recognition||listening)return;const delay=recognitionRestartAfter-Date.now();if(delay>0){setTimeout(startRecognition,delay);return;}if(!running)startPanel();resumeListening=true;try{recognition.start();}catch(e){}}
function stopRecognition(temporary){if(!temporary)resumeListening=false;if(recognition&&listening){try{recognition.abort();}catch(e){}}}
micBtn.onclick=()=>{if(listening||resumeListening)stopRecognition(false);else startRecognition();};setupRecognition();

saveBtn.onclick=()=>{const lines=['# Panel Mode transcript','',`**Topic:** ${document.getElementById('topic').value.trim()||'Open conversation'}`,''];materials.forEach(s=>lines.push(`**Shared ${s.kind}:** ${s.label}`));lines.push('');history.forEach(item=>lines.push('**'+(item.speaker==='user'?'Alex':ROBOTS[item.speaker].name)+':** '+item.text+'\n'));const blob=new Blob([lines.join('\n')],{type:'text/markdown'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='panel-transcript-'+new Date().toISOString().slice(0,10)+'.md';document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},0);};

function initLocalHeads(){if(DRIVES_SERVER_HEADS)return;if(typeof WEBSERIAL_OK==='undefined'||!WEBSERIAL_OK)return;document.querySelectorAll('[data-connect]').forEach(button=>{button.style.display='inline-block';button.onclick=async()=>{const id=button.dataset.connect;await connectHead(ROBOTS[id].head);button.textContent=(typeof LOCAL_DRIVERS!=='undefined'&&LOCAL_DRIVERS[ROBOTS[id].head])?'Local head connected':'Connect local head';};});}
window.onLocalHeadsChanged=initLocalHeads;window.onLocalHeadsNote=message=>addNote(message);initLocalHeads();
window.addEventListener('beforeunload',()=>{stopRecognition(false);stopAudio();});
</script>
</body>
</html>"""
