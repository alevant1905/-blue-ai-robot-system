"""Pure HTML template for the three-robot Comedic Banter page."""

BANTER_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Comedic Banter — Blue, Hexia &amp; Casper</title>
<link rel="stylesheet" href="/assets/blue.css">
<script src="/assets/blue.js" defer></script>
<style>
:root{
  --bluec:#3da9fc;--hexiac:#b06cf0;--casperc:#f28c28;
  --cream:#faf8f4;--paper:#fff;--ink:#1a2e1a;--forest:#4a6b4a;
  --sage:#8fae8f;--slate:#64748b;--blue:#3b82f6;--gold:#d4af37;
  --line:#cfc9bd;--shadow:0 1px 3px rgba(0,0,0,.06)
}
body{font-family:-apple-system,'Segoe UI',sans-serif;background:var(--cream);color:var(--ink);
  max-width:860px;margin:0 auto;padding:26px 18px;line-height:1.5}
h1{font-size:1.62em;margin:0 0 4px}
.sub{color:var(--slate);margin:0 0 16px;font-size:.95em}
.panel{background:var(--paper);border:1px solid var(--line);border-radius:14px;
  padding:15px;margin-bottom:15px;box-shadow:var(--shadow)}
.controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:8px 0}
input[type=text]{flex:1;min-width:260px;padding:11px 13px;border:1px solid var(--line);
  border-radius:9px;background:var(--paper);color:var(--ink);font:inherit}
select,button{padding:9px 12px;border:1px solid var(--line);border-radius:8px;
  background:var(--paper);color:var(--ink);font:inherit;cursor:pointer}
button.primary{background:#1a2e1a;color:#fff;border-color:#1a2e1a}
button:disabled{opacity:.48;cursor:default}
.muted{color:var(--slate);font-size:.88em}
.energy{display:flex;align-items:center;gap:9px;flex:1;min-width:250px}
.energy input{flex:1}
.voice-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:12px}
.voice-card{border:1px solid var(--line);border-radius:10px;padding:9px;min-width:0}
.voice-card b{display:block;margin-bottom:6px}
.voice-card .reg{font-weight:400;font-size:.78em;color:var(--slate);letter-spacing:.04em}
.voice-card.blue b{color:var(--bluec)}.voice-card.hexia b{color:var(--hexiac)}
.voice-card.pico b{color:var(--casperc)}
.voice-card select{width:100%;margin-top:5px}
#status{min-height:1.5em;margin:8px 2px;color:var(--slate);font-size:.9em}
#status.error{color:#c2413a}
#log{display:flex;flex-direction:column;gap:11px;margin:14px 0 80px}
.turn{padding:11px 15px;border-radius:15px;max-width:82%;box-shadow:var(--shadow)}
.turn .who{font-size:.7em;text-transform:uppercase;letter-spacing:.09em;font-weight:700;margin-bottom:3px}
.turn.blue{align-self:flex-start;background:#eaf4ff;border:1px solid #cfe4fb}
.turn.blue .who{color:var(--bluec)}
.turn.hexia{align-self:flex-end;background:#f4ecfc;border:1px solid #e6d6f7}
.turn.hexia .who{color:var(--hexiac)}
.turn.pico{align-self:center;background:#fff2e4;border:1px solid #f5d2ad}
.turn.pico .who{color:var(--casperc)}
.turn.speaking{box-shadow:0 0 0 2px currentColor, var(--shadow)}
.note{align-self:center;color:var(--slate);font-size:.82em;text-align:center;
  padding:4px 10px;border-radius:999px;background:rgba(100,116,139,.08)}
:root:not([data-theme="light"]) .turn.blue{background:rgba(61,169,252,.12);border-color:rgba(61,169,252,.35)}
:root:not([data-theme="light"]) .turn.hexia{background:rgba(176,108,240,.12);border-color:rgba(176,108,240,.35)}
:root:not([data-theme="light"]) .turn.pico{background:rgba(242,140,40,.12);border-color:rgba(242,140,40,.35)}
@media(max-width:680px){
  .voice-grid{grid-template-columns:1fr}.turn{max-width:91%}
}
</style>
</head>
<body>
<h1>Comedic Banter</h1>
<p class="sub">Give Blue, Hexia, and Casper a topic. They riff in a shifting order—nobody twice in a row, nobody left out—build callbacks, and land the routine together. Blue talks like a boomer, Hexia like Gen X, Casper like Gen Z, each with their own voice, face, and head.</p>

<div class="panel">
  <div class="controls">
    <input id="topic" type="text" maxlength="500" placeholder="Give them a topic — e.g. why printers can sense fear">
  </div>
  <div class="controls">
    <label class="muted">Length
      <select id="turns">
        <option value="6">6 turns · quick bit</option>
        <option value="9" selected>9 turns · full riff</option>
        <option value="12">12 turns · extended</option>
        <option value="15">15 turns · long set</option>
      </select>
    </label>
    <label class="muted">First up
      <select id="starter">
        <option value="random" selected>Surprise me</option>
        <option value="blue">Blue</option>
        <option value="hexia">Hexia</option>
        <option value="pico">Casper</option>
      </select>
    </label>
    <label class="energy muted">Energy
      <input id="energy" type="range" min="0" max="10" step="1" value="6">
      <span id="energyLabel">lively</span>
    </label>
  </div>
  <div class="voice-grid">
    <div class="voice-card blue"><b>Blue <span class="reg">boomer</span></b>
      <select id="voice-blue" aria-label="Blue voice"></select>
      <select id="rate-blue" aria-label="Blue speaking speed">
        <option value="auto">Default speed</option><option value="0.75">Slower</option>
        <option value="0.9">Relaxed</option><option value="1.0">Normal</option>
        <option value="1.15">Brisk</option><option value="1.3">Fast</option>
      </select>
    </div>
    <div class="voice-card hexia"><b>Hexia <span class="reg">Gen X</span></b>
      <select id="voice-hexia" aria-label="Hexia voice"></select>
      <select id="rate-hexia" aria-label="Hexia speaking speed">
        <option value="auto">Default speed</option><option value="0.75">Slower</option>
        <option value="0.9">Relaxed</option><option value="1.0">Normal</option>
        <option value="1.15">Brisk</option><option value="1.3">Fast</option>
      </select>
    </div>
    <div class="voice-card pico"><b>Casper <span class="reg">Gen Z</span></b>
      <select id="voice-pico" aria-label="Casper voice"></select>
      <select id="rate-pico" aria-label="Casper speaking speed">
        <option value="auto">Default speed</option><option value="0.75">Slower</option>
        <option value="0.9">Relaxed</option><option value="1.0">Normal</option>
        <option value="1.15">Brisk</option><option value="1.3">Fast</option>
      </select>
    </div>
  </div>
  <div class="controls" style="margin-top:14px">
    <button class="primary" id="startBtn">Start banter</button>
    <button id="pauseBtn" disabled>Pause</button>
    <button id="stopBtn" disabled>Stop</button>
    <button id="saveBtn" disabled>Save transcript</button>
    <label class="muted"><input id="speakChk" type="checkbox" checked> speak aloud</label>
    <label class="muted" title="Keep private family and household details out of the routine"><input id="noFamilyChk" type="checkbox" checked> no family refs</label>
  </div>
  <div id="status">Ready for a topic.</div>
</div>

<div id="log" aria-live="polite"></div>
<audio id="banterAudio" preload="auto"></audio>
<script src="/js/ohbot-heads.js"></script>
<script>
const ROBOTS={{ robots_json|safe }};
const ROBOT_IDS=['blue','hexia','pico'];
const logEl=document.getElementById('log');
const statusEl=document.getElementById('status');
const startBtn=document.getElementById('startBtn');
const pauseBtn=document.getElementById('pauseBtn');
const stopBtn=document.getElementById('stopBtn');
const saveBtn=document.getElementById('saveBtn');
const audioEl=document.getElementById('banterAudio');
const DRIVES_SERVER_HEADS=(typeof blueDeviceTag==='function')?(blueDeviceTag()==='windows'):true;

let running=false,paused=false,history=[],transcript=[],sessionId='',sessionEnded=true;
let pauseWaiters=[],activeFinish=null,audioUrl='',audioAbort=null;
let neuralVoices=[];
const serverPrefs={blue:{provider:'browser',voice:''},hexia:{provider:'browser',voice:''},pico:{provider:'browser',voice:''}};

function setStatus(text,error){
  statusEl.textContent=text||'';statusEl.className=error?'error':'';
}
function addNote(text){
  const el=document.createElement('div');el.className='note';el.textContent=text;
  logEl.appendChild(el);window.scrollTo(0,document.body.scrollHeight);
}
function addTurn(cfg,text){
  const el=document.createElement('div');el.className='turn '+cfg.id;
  const who=document.createElement('div');who.className='who';who.textContent=cfg.name;
  const body=document.createElement('div');body.textContent=text;
  el.appendChild(who);el.appendChild(body);logEl.appendChild(el);
  transcript.push({name:cfg.name,text:text});saveBtn.disabled=false;
  window.scrollTo(0,document.body.scrollHeight);return el;
}
function energyWord(n){
  n=+n;return n<=2?'gentle':n<=4?'warm':n<=7?'lively':n<=8?'spirited':'chaotic';
}
document.getElementById('energy').addEventListener('input',function(){
  document.getElementById('energyLabel').textContent=energyWord(this.value);
});

function browserVoices(){
  const voices=(window.speechSynthesis&&window.speechSynthesis.getVoices())||[];
  return voices.filter(v=>/^(en|fr|ru|el|da)/i.test(v.lang||''));
}
function voiceRate(id){
  let saved='';try{saved=localStorage.getItem('blueVoiceRate_'+id)||'';}catch(e){}
  const n=parseFloat(saved);return saved&&!isNaN(n)?n:((ROBOTS[id]&&ROBOTS[id].voiceRate)||1);
}
function pickedBrowserVoice(id){
  let name='';try{name=localStorage.getItem('blueVoiceName_'+id)||'';}catch(e){}
  const voices=browserVoices();
  if(name){const found=voices.find(v=>v.name===name);if(found)return found;}
  const cfg=ROBOTS[id]||{};
  const genderNames=cfg.preferFemale?
    ['Samantha','Victoria','Karen','Microsoft Zira','Google UK English Female']:
    ['Daniel','Aaron','Arthur','Microsoft David','Google UK English Male'];
  for(const wanted of genderNames){
    const found=voices.find(v=>v.name===wanted||v.name.indexOf(wanted)===0);if(found)return found;
  }
  return voices.find(v=>/^en/i.test(v.lang||''))||voices[0]||null;
}
function saveVoice(id,provider,voice){
  serverPrefs[id]={provider:provider,voice:voice||''};
  fetch('/tts/preferences/'+id,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(serverPrefs[id])}).catch(()=>{});
}
function stopAudioOnly(){
  try{window.speechSynthesis.cancel();}catch(e){}
  if(audioAbort){try{audioAbort.abort();}catch(e){}audioAbort=null;}
  try{audioEl.pause();audioEl.removeAttribute('src');audioEl.load();}catch(e){}
  if(audioUrl){try{URL.revokeObjectURL(audioUrl);}catch(e){}audioUrl='';}
}
function previewVoice(id){
  if(running)return;
  stopAudioOnly();
  const cfg=ROBOTS[id],pref=serverPrefs[id]||{};
  const text="Hi, I'm "+cfg.name+". Ready to riff.";
  if(pref.provider==='edge'&&pref.voice){
    fetch('/tts/synthesize',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:text,voice:pref.voice,rate:voiceRate(id),pitch:cfg.voicePitch||1})})
      .then(r=>{if(!r.ok)throw new Error();return r.blob();})
      .then(blob=>{audioUrl=URL.createObjectURL(blob);audioEl.src=audioUrl;return audioEl.play();})
      .catch(()=>{});
    return;
  }
  try{
    const u=new SpeechSynthesisUtterance(text),v=pickedBrowserVoice(id);
    if(v){u.voice=v;u.lang=v.lang||'en-US';}u.rate=voiceRate(id);u.pitch=cfg.voicePitch||1;
    window.speechSynthesis.speak(u);
  }catch(e){}
}
function buildVoicePickers(){
  const device=browserVoices();
  ROBOT_IDS.forEach(id=>{
    const select=document.getElementById('voice-'+id);if(!select)return;
    select.innerHTML='';
    if(neuralVoices.length){
      const group=document.createElement('optgroup');group.label='Neural voices · every device';
      neuralVoices.forEach(v=>{
        const option=document.createElement('option');option.value='edge:'+v.id;
        option.textContent=v.name+' ('+v.locale+', '+v.gender+')';
        if(serverPrefs[id].provider==='edge'&&serverPrefs[id].voice===v.id)option.selected=true;
        group.appendChild(option);
      });select.appendChild(group);
    }
    const group=document.createElement('optgroup');group.label='Device voices · offline';
    const automatic=document.createElement('option');automatic.value='browser:';
    automatic.textContent='Automatic device voice';group.appendChild(automatic);
    let saved='';try{saved=localStorage.getItem('blueVoiceName_'+id)||'';}catch(e){}
    device.forEach(v=>{
      const option=document.createElement('option');option.value='browser:'+v.name;
      option.textContent=v.name+' ('+v.lang+')';
      if(serverPrefs[id].provider==='browser'&&saved===v.name)option.selected=true;
      group.appendChild(option);
    });select.appendChild(group);
    select.onchange=()=>{
      if(select.value.indexOf('edge:')===0){
        saveVoice(id,'edge',select.value.slice(5));
      }else{
        const name=select.value.slice(8);
        try{name?localStorage.setItem('blueVoiceName_'+id,name):localStorage.removeItem('blueVoiceName_'+id);}catch(e){}
        saveVoice(id,'browser',name);
      }
      previewVoice(id);
    };
  });
}
async function loadVoices(){
  try{
    const results=await Promise.all(ROBOT_IDS.map(id=>
      fetch('/tts/preferences/'+id).then(r=>r.json()).catch(()=>null)
    ).concat([fetch('/tts/voices?lang=en').then(r=>r.json()).catch(()=>null)]));
    ROBOT_IDS.forEach((id,index)=>{
      const pref=results[index];if(pref&&pref.ok)serverPrefs[id]={provider:pref.provider,voice:pref.voice||''};
    });
    const catalog=results[ROBOT_IDS.length];
    if(catalog&&catalog.ok&&Array.isArray(catalog.voices))neuralVoices=catalog.voices;
  }catch(e){}
  buildVoicePickers();
}
ROBOT_IDS.forEach(id=>{
  const rate=document.getElementById('rate-'+id);let saved='';
  try{saved=localStorage.getItem('blueVoiceRate_'+id)||'';}catch(e){}
  rate.value=saved||'auto';if(!rate.value)rate.value='auto';
  rate.onchange=()=>{
    try{rate.value==='auto'?localStorage.removeItem('blueVoiceRate_'+id):localStorage.setItem('blueVoiceRate_'+id,rate.value);}catch(e){}
    previewVoice(id);
  };
});
if(window.speechSynthesis)window.speechSynthesis.onvoiceschanged=buildVoicePickers;
buildVoicePickers();loadVoices();

function cleanSpeech(text){
  return String(text||'').replace(/[*_`#]/g,'').replace(/\s+/g,' ').trim();
}
function lipFrames(text,rate){
  const words=(text.match(/[^\s]+/g)||[]),frames=[],scale=1/(rate||1);
  words.forEach(word=>{
    const core=word.replace(/[^A-Za-z0-9\u00C0-\u024F]/g,'');
    const duration=Math.min(.72,Math.max(.14,Math.max(1,core.length)*.058))*scale;
    const moves=Math.max(1,Math.round(Math.max(1,core.length)/3)),per=duration/moves;
    for(let i=0;i<moves;i++){frames.push([.58+Math.random()*.4,per*.62]);frames.push([.08,per*.38]);}
    const last=word.slice(-1);frames.push([0,(/[.!?]/.test(last)?.38:/[,;:]/.test(last)?.2:.055)*scale]);
  });return frames;
}
function localCall(name,args){
  try{return typeof window[name]==='function'&&window[name].apply(window,args);}catch(e){return false;}
}
function headLip(cfg,frames){
  if(localCall('localHeadLip',[cfg.head,frames]))return;
  if(!DRIVES_SERVER_HEADS)return;
  fetch('/head/'+cfg.head+'/lip-seq',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({frames:frames})}).catch(()=>{});
}
function headLipStop(cfg){
  if(localCall('localHeadLipStop',[cfg.head]))return;
  if(!DRIVES_SERVER_HEADS)return;
  fetch('/head/'+cfg.head+'/lip',{method:'POST',headers:{'Content-Type':'application/json'},
    body:'{"on":false}'}).catch(()=>{});
}
function headMood(cfg,mood){
  if(!mood)return;
  const body={r:mood.r|0,g:mood.g|0,b:mood.b|0,name:mood.name||'neutral',
    expression:mood.expression||mood.name||'neutral'};
  if(cfg.headDriver!=='picoh'&&localCall('localHeadControl',[cfg.head,'/head/eye-color',body]))return;
  if(!DRIVES_SERVER_HEADS)return;
  const path=cfg.headDriver==='picoh'?'/mood':'/eye-color';
  fetch('/head/'+cfg.head+path,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body)}).catch(()=>{});
}
function headRest(cfg){
  headMood(cfg,{r:0,g:0,b:0,name:'neutral',expression:'neutral'});
}
function headGesture(cfg,gesture){
  if(!gesture)return;const body={action:gesture,times:2};
  if(localCall('localHeadControl',[cfg.head,'/head/action',body]))return;
  if(!DRIVES_SERVER_HEADS)return;
  fetch('/head/'+cfg.head+'/action',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body)}).catch(()=>{});
}
function speakAs(cfg,text,el,mood,gesture){
  return new Promise(resolve=>{
    const spoken=cleanSpeech(text),rate=voiceRate(cfg.id),frames=lipFrames(spoken,rate);
    const estimate=frames.reduce((sum,frame)=>sum+frame[1],0)*1000;
    let done=false,started=false,keepAlive=null;
    const embody=()=>{
      if(started)return;started=true;el.classList.add('speaking');
      headLip(cfg,frames);headMood(cfg,mood);headGesture(cfg,gesture);
    };
    const finish=()=>{
      if(done)return;done=true;if(activeFinish===finish)activeFinish=null;
      if(keepAlive)clearInterval(keepAlive);stopAudioOnly();
      if(started){headLipStop(cfg);headRest(cfg);el.classList.remove('speaking');}
      resolve();
    };
    activeFinish=finish;
    if(!document.getElementById('speakChk').checked){
      embody();setTimeout(finish,Math.max(1300,estimate+350));return;
    }
    const speakBrowser=()=>{
      if(done)return;embody();
      try{
        const utterance=new SpeechSynthesisUtterance(spoken),voice=pickedBrowserVoice(cfg.id);
        if(voice){utterance.voice=voice;utterance.lang=voice.lang||'en-US';}
        utterance.rate=rate;utterance.pitch=cfg.voicePitch||1;
        utterance.onend=finish;utterance.onerror=finish;
        window.speechSynthesis.speak(utterance);
        keepAlive=setInterval(()=>{try{if(window.speechSynthesis.speaking){window.speechSynthesis.pause();window.speechSynthesis.resume();}}catch(e){}},9000);
      }catch(e){finish();}
    };
    const pref=serverPrefs[cfg.id]||{};
    if(pref.provider==='edge'&&pref.voice){
      audioAbort=(typeof AbortController!=='undefined')?new AbortController():null;
      const options={method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({text:spoken,voice:pref.voice,rate:rate,pitch:cfg.voicePitch||1})};
      if(audioAbort)options.signal=audioAbort.signal;
      fetch('/tts/synthesize',options).then(r=>{if(!r.ok)throw new Error();return r.blob();})
        .then(blob=>{
          if(done)return;audioUrl=URL.createObjectURL(blob);audioEl.src=audioUrl;
          audioEl.onended=finish;audioEl.onerror=finish;embody();return audioEl.play();
        }).catch(error=>{if(!done&&(!error||error.name!=='AbortError'))speakBrowser();});
    }else{speakBrowser();}
    setTimeout(finish,Math.max(25000,estimate*2.5+9000));
  });
}
function cancelCurrentSpeech(){if(activeFinish)activeFinish();else stopAudioOnly();}

function waitIfPaused(){
  if(!paused)return Promise.resolve();
  return new Promise(resolve=>pauseWaiters.push(resolve));
}
function setPaused(value){
  paused=!!value;pauseBtn.textContent=paused?'Continue':'Pause';
  setStatus(paused?'Paused after this line.':'Banter running…');
  if(!paused){const waiters=pauseWaiters.slice();pauseWaiters=[];waiters.forEach(resolve=>resolve());}
}
pauseBtn.onclick=()=>{if(running)setPaused(!paused);};

async function endSession(){
  if(sessionEnded||!sessionId)return;sessionEnded=true;
  try{await fetch('/banter/session/end',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({sessionId:sessionId})});}catch(e){}
}
async function stopRun(message){
  running=false;setPaused(false);cancelCurrentSpeech();await endSession();
  startBtn.disabled=false;pauseBtn.disabled=true;stopBtn.disabled=true;
  setStatus(message||'Stopped.');
}
stopBtn.onclick=()=>stopRun('Stopped.');

/* Same rules as banter_lineup() on the server: nobody twice in a row, nobody
   silent for four turns, and no two robots allowed to ping-pong the third out.
   Kept here only as a fallback if /banter/lineup cannot be reached. */
function localLineup(starter,total){
  const base=['blue','hexia','pico'];
  if(base.indexOf(starter)<0)starter=base[Math.floor(Math.random()*base.length)];
  const line=[starter];
  while(line.length<total){
    const at=line.length;
    let options=base.filter(r=>r!==line[at-1]);
    if(at>=3&&line[at-1]===line[at-3]){
      const kept=options.filter(r=>r!==line[at-2]);if(kept.length)options=kept;
    }
    const gap={};options.forEach(r=>{const seen=line.lastIndexOf(r);gap[r]=seen<0?at+1:at-seen;});
    const starved=options.filter(r=>gap[r]>=4);if(starved.length)options=starved;
    let weight=0;options.forEach(r=>{weight+=gap[r]*gap[r];});
    let roll=Math.random()*weight,pick=options[options.length-1];
    for(const r of options){roll-=gap[r]*gap[r];if(roll<=0){pick=r;break;}}
    line.push(pick);
  }
  return line;
}
async function fetchLineup(starter,total){
  try{
    const response=await fetch('/banter/lineup',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({starter:starter,turns:total})});
    const data=await response.json();
    if(response.ok&&data&&Array.isArray(data.lineup)&&data.lineup.length>=total)return data.lineup;
  }catch(e){}
  return localLineup(starter,total);
}
async function runBanter(){
  const topic=document.getElementById('topic').value.trim();
  if(!topic){setStatus('Give them a topic first.',true);document.getElementById('topic').focus();return;}
  running=true;paused=false;history=[];transcript=[];logEl.innerHTML='';
  sessionId='banter-'+Date.now()+'-'+Math.random().toString(36).slice(2,8);sessionEnded=false;
  const total=parseInt(document.getElementById('turns').value,10)||9;
  const energy=parseInt(document.getElementById('energy').value,10)||6;
  startBtn.disabled=true;pauseBtn.disabled=false;stopBtn.disabled=false;saveBtn.disabled=true;
  addNote('Topic: '+topic+' · '+total+' turns · '+energyWord(energy)+' energy');
  setStatus('Working out who jumps in first…');
  const lineup=await fetchLineup(document.getElementById('starter').value,total);
  if(!running)return;
  setStatus('Warming up the first riff…');
  try{await fetch('/banter/session/start',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({sessionId:sessionId})});}catch(e){}
  for(let index=0;index<total&&running;index++){
    await waitIfPaused();if(!running)break;
    const speaker=lineup[index]||lineup[index%lineup.length],cfg=ROBOTS[speaker];
    setStatus(cfg.name+' is thinking of the next beat…');
    let data=null;
    for(let attempt=0;attempt<2&&running;attempt++){
      try{
        const response=await fetch('/banter/turn',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({sessionId:sessionId,speaker:speaker,topic:topic,history:history,
            turnIndex:index,plannedTurns:total,energy:energy,
            noFamily:document.getElementById('noFamilyChk').checked})});
        data=await response.json().catch(()=>null);
        if(response.ok&&data&&data.text)break;
      }catch(e){data=null;}
      if(attempt===0)addNote(cfg.name+' missed the beat—trying that turn once more.');
    }
    if(!running)break;
    if(!data||!data.text){
      await stopRun('The routine stopped because '+cfg.name+' could not generate a line.');
      return;
    }
    const el=addTurn(cfg,data.text);history.push({speaker:speaker,text:data.text});
    setStatus(cfg.name+' is speaking…');
    await speakAs(cfg,data.text,el,data.eye_mood,data.head_gesture);
  }
  if(running){
    running=false;await endSession();startBtn.disabled=false;pauseBtn.disabled=true;stopBtn.disabled=true;
    setStatus('That is the set. Give them another topic whenever you like.');
    addNote('End of set.');
  }
}
startBtn.onclick=runBanter;
document.getElementById('topic').addEventListener('keydown',event=>{
  if(event.key==='Enter'&&!running)runBanter();
});
saveBtn.onclick=()=>{
  if(!transcript.length)return;
  const topic=document.getElementById('topic').value.trim();
  const lines=['# Comedic Banter','',`**Topic:** ${topic}`,''];
  transcript.forEach(turn=>{lines.push('**'+turn.name+':** '+turn.text,'');});
  const blob=new Blob([lines.join('\n')],{type:'text/markdown;charset=utf-8'});
  const url=URL.createObjectURL(blob),link=document.createElement('a');
  link.href=url;link.download='comedic-banter-'+new Date().toISOString().slice(0,10)+'.md';
  document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);
};
window.addEventListener('beforeunload',()=>{cancelCurrentSpeech();if(!sessionEnded&&sessionId){
  try{navigator.sendBeacon('/banter/session/end',new Blob([JSON.stringify({sessionId:sessionId})],{type:'application/json'}));}catch(e){}
}});
</script>
</body>
</html>
"""
