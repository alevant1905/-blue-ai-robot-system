"""The /jspace page — talk with Blue-J and watch his inner workspace evolve.

Kept deliberately spare: a chat column and, beside it, the J-space itself —
the persistent workspace his background deliberation keeps rewriting, with a
log of what each silent pass changed. The inner life is the exhibit."""

JSPACE_HTML = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blue-J — J-space</title>
<style>
 :root{--paper:#fbf9f4;--ink:#22301f;--line:#d8d2c4;--slate:#6b7280;--forest:#1a5e3a;--jay:#2458a6}
 body{font-family:Georgia,'Times New Roman',serif;background:var(--paper);color:var(--ink);margin:0;padding:18px}
 .wrap{max-width:1100px;margin:0 auto}
 h1{font-size:1.35em;margin:0 0 2px}
 .muted{color:var(--slate);font-size:.9em}
 .cols{display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap;margin-top:14px}
 .chatcol{flex:3;min-width:340px}
 .wscol{flex:2;min-width:300px;position:sticky;top:12px}
 #log{display:flex;flex-direction:column;gap:10px;min-height:120px}
 .turn{padding:10px 14px;border-radius:14px;max-width:88%;box-shadow:0 1px 2px rgba(0,0,0,.06)}
 .turn.you{align-self:flex-end;background:#eef2e6;border:1px solid #d5dec3}
 .turn.bj{align-self:flex-start;background:#e8eefb;border:1px solid #c8d7f2}
 .turn .who{font-size:.68em;text-transform:uppercase;letter-spacing:.08em;font-weight:700;margin-bottom:3px;color:var(--jay)}
 .turn.you .who{color:var(--forest)}
 .inrow{display:flex;gap:8px;margin-top:12px}
 #msg{flex:1;padding:10px 12px;border:1px solid var(--line);border-radius:8px;font:inherit}
 button{padding:9px 14px;border:1px solid var(--line);border-radius:8px;background:#fff;font:inherit;cursor:pointer;color:var(--ink)}
 button.primary{background:var(--jay);color:#fff;border-color:var(--jay)}
 button:disabled{opacity:.5;cursor:default}
 #wsPanel{border:1px dashed var(--line);border-radius:10px;padding:12px 14px;background:#fff}
 #wsPanel h2{font-size:.95em;margin:0 0 8px;color:var(--jay)}
 .wsrow{margin:5px 0;font-size:.9em;line-height:1.5}
 .wsrow b{color:var(--jay);font-size:.8em;text-transform:uppercase;letter-spacing:.05em}
 .wsstamp{font-size:.76em;color:var(--slate);margin-top:8px}
 #thoughts{margin-top:12px;border-top:1px solid var(--line);padding-top:8px}
 #thoughts .t{font-size:.8em;color:var(--slate);margin:4px 0}
 #thoughts .t .k{color:var(--jay)}
 .note{color:var(--slate);font-size:.85em;font-style:italic}
</style></head><body><div class="wrap">
<h1>Blue-J <span class="muted">— an experiment in inner life</span></h1>
<div class="muted">A separate sibling of Blue: no household memory, no tools — just a conversation and a
persistent J-space his own background deliberation keeps rewriting, even while no one is here.</div>

<div class="cols">
 <div class="chatcol">
  <div id="log"></div>
  <div class="inrow">
   <input id="msg" type="text" placeholder="Say something to Blue-J" autocomplete="off">
   <button class="primary" id="sendBtn">Send</button>
  </div>
  <div class="note" id="status"></div>
 </div>
 <div class="wscol">
  <div id="wsPanel">
   <h2>🧠 His J-space (live)</h2>
   <div id="wsBody" class="muted">loading…</div>
   <div class="wsstamp" id="wsStamp"></div>
   <div id="thoughts"></div>
   <div style="margin-top:10px"><button id="resetBtn" title="Archive this inner life and start a fresh one">Reset J-space</button></div>
  </div>
 </div>
</div>

<script>
let history=[];
try{ history=JSON.parse(localStorage.getItem('jspace.history.v1')||'[]')||[]; }catch(e){ history=[]; }
const logEl=document.getElementById('log'), msgEl=document.getElementById('msg');
const sendBtn=document.getElementById('sendBtn'), statusEl=document.getElementById('status');

function addTurn(role,text){
  const d=document.createElement('div'); d.className='turn '+(role==='assistant'?'bj':'you');
  const w=document.createElement('div'); w.className='who'; w.textContent=(role==='assistant'?'Blue-J':'You');
  const x=document.createElement('div'); x.textContent=text;
  d.appendChild(w); d.appendChild(x); logEl.appendChild(d);
  window.scrollTo(0,document.body.scrollHeight);
}
history.slice(-40).forEach(function(h){ addTurn(h.role,h.text); });

function saveHistory(){ try{ localStorage.setItem('jspace.history.v1',JSON.stringify(history.slice(-60))); }catch(e){} }

async function send(){
  const text=(msgEl.value||'').trim(); if(!text) return;
  msgEl.value=''; sendBtn.disabled=true; statusEl.textContent='thinking…';
  addTurn('user',text); history.push({role:'user',text:text}); saveHistory();
  let j=null;
  try{ j=await (await fetch('/jspace/chat',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({message:text,history:history.slice(0,-1)})})).json(); }catch(e){}
  sendBtn.disabled=false;
  if(!j||!j.ok){ statusEl.textContent=(j&&j.error)?j.error:'no reply — is the server up?'; return; }
  statusEl.textContent='';
  addTurn('assistant',j.reply); history.push({role:'assistant',text:j.reply}); saveHistory();
  setTimeout(refreshWs, 4000);   // his deliberation pass usually lands shortly after
  setTimeout(refreshWs, 15000);
}
sendBtn.addEventListener('click',send);
msgEl.addEventListener('keydown',function(e){ if(e.key==='Enter') send(); });

async function refreshWs(){
  let j=null;
  try{ j=await (await fetch('/jspace/state')).json(); }catch(e){ return; }
  if(!j||!j.ok) return;
  const b=document.getElementById('wsBody'); b.innerHTML=''; b.classList.remove('muted');
  (j.workspace||'').split('\n').forEach(function(x){
    x=x.trim(); if(!x) return;
    const m=/^([A-Z][A-Z \-]{2,}):\s*(.*)$/.exec(x);
    const d=document.createElement('div'); d.className='wsrow';
    if(m){ const k=document.createElement('b'); k.textContent=m[1]+': '; d.appendChild(k); d.appendChild(document.createTextNode(m[2])); }
    else{ d.textContent=x; }
    b.appendChild(d);
  });
  document.getElementById('wsStamp').textContent=
    'revised '+String(j.updated||'?').slice(0,16).replace('T',' ')+' — '+j.passes+' deliberation passes'
    +(j.ruminations_left?(' — still ruminating ('+j.ruminations_left+' passes left)'):'');
  const t=document.getElementById('thoughts'); t.innerHTML='';
  const lg=(j.log||[]).slice().reverse();
  if(lg.length){
    const h=document.createElement('div'); h.className='t'; h.innerHTML='<span class="k">recent silent thoughts:</span>'; t.appendChild(h);
    lg.forEach(function(e){
      const d=document.createElement('div'); d.className='t';
      d.textContent=String(e.at||'').slice(11,16)+' ['+(e.trigger||'?')+'] '+(e.changed||'');
      t.appendChild(d);
    });
  }
}
document.getElementById('resetBtn').addEventListener('click',async function(){
  if(!confirm('Archive this inner life and start a fresh one? The current J-space is saved to disk first.')) return;
  try{ const j=await (await fetch('/jspace/reset',{method:'POST'})).json();
       if(j&&j.ok){ history=[]; saveHistory(); logEl.innerHTML=''; refreshWs(); } }catch(e){}
});
refreshWs();
setInterval(refreshWs, 20000);   // watch the idle deliberation land while you're away
</script>
</div></body></html>"""
