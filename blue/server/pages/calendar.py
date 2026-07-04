"""Extracted verbatim from bluetools.py (see blue/server/pages).

Do not import bluetools here; this module is pure data.
"""

CALENDAR_HTML = r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Calendar - Blue</title>
    <link rel="stylesheet" href="/assets/blue.css">
    <script src="/assets/blue.js" defer></script>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Playfair+Display:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --cream:#faf8f4; --paper:#ffffff; --ink:#1a2e1a; --forest:#4a6b4a;
            --sage:#8fae8f; --slate:#64748b; --blue:#3b82f6; --gold:#d4af37;
            --line:rgba(143,174,143,0.32); --shadow:0 8px 24px rgba(26,46,26,0.06);
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body { font-family:'IBM Plex Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
               background:var(--cream); color:var(--ink); line-height:1.5; padding:28px 18px; }
        .wrap { max-width:1040px; margin:0 auto; }
        .topbar { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-bottom:18px; }
        .title-group h1 { font-family:'Playfair Display',Georgia,serif; font-weight:700; font-size:1.8em; letter-spacing:-0.01em; }
        .title-group::before { content:""; display:block; width:56px; height:3px;
            background:linear-gradient(90deg,var(--gold),var(--blue)); margin-bottom:12px; }
        .title-group .links { margin-top:4px; }
        .title-group .links a { color:var(--forest); text-decoration:none; font-weight:500; margin-right:16px; font-size:0.9em; }
        .title-group .links a:hover { color:var(--ink); text-decoration:underline; }
        .nav { display:flex; align-items:center; gap:10px; }
        .nav .month-label { font-family:'Playfair Display',Georgia,serif; font-size:1.25em; min-width:170px; text-align:center; }
        button { font-family:inherit; cursor:pointer; }
        .btn { border:1px solid var(--sage); background:var(--paper); color:var(--forest);
               border-radius:8px; padding:9px 14px; font-size:0.9em; font-weight:500; transition:background .2s,border-color .2s; }
        .btn:hover { background:var(--cream); border-color:var(--forest); }
        .btn-primary { background:var(--ink); color:#fff; border-color:var(--ink); }
        .btn-primary:hover { background:var(--forest); border-color:var(--forest); }
        .btn-icon { width:38px; height:38px; padding:0; font-size:1.1em; line-height:1; }
        .grid { background:var(--paper); border:1px solid var(--line); border-radius:12px; box-shadow:var(--shadow); overflow:hidden; }
        .dow-row { display:grid; grid-template-columns:repeat(7,1fr); background:var(--cream); border-bottom:1px solid var(--line); }
        .dow-row div { padding:10px 6px; text-align:center; font-family:'IBM Plex Mono',monospace;
            font-size:0.68em; text-transform:uppercase; letter-spacing:0.1em; color:var(--slate); }
        .weeks { display:grid; grid-template-columns:repeat(7,1fr); }
        .cell { min-height:96px; border-right:1px solid var(--line); border-bottom:1px solid var(--line);
            padding:6px; cursor:pointer; position:relative; transition:background .12s; overflow:hidden; }
        .cell:nth-child(7n) { border-right:none; }
        .cell:hover { background:var(--cream); }
        .cell.other { background:#f5f3ee; color:#b5bcb0; }
        .cell.selected { outline:2px solid var(--forest); outline-offset:-2px; }
        .cell .num { font-size:0.85em; font-weight:500; }
        .cell.today .num { background:var(--ink); color:#fff; border-radius:50%; width:24px; height:24px;
            display:inline-flex; align-items:center; justify-content:center; }
        .ev { font-size:0.72em; margin-top:3px; padding:2px 6px; border-radius:5px; background:#eef2ec;
            border-left:3px solid var(--forest); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .ev.rec { border-left-color:var(--blue); background:#eef3fb; }
        .more { font-size:0.68em; color:var(--slate); margin-top:2px; font-family:'IBM Plex Mono',monospace; }
        .day-panel { background:var(--paper); border:1px solid var(--line); border-radius:12px;
            box-shadow:var(--shadow); margin-top:18px; padding:20px 22px; }
        .day-panel h2 { font-family:'Playfair Display',Georgia,serif; font-size:1.25em; margin-bottom:14px; }
        .ev-row { display:flex; align-items:center; gap:12px; padding:11px 0; border-bottom:1px solid var(--line); cursor:pointer; }
        .ev-row:last-child { border-bottom:none; }
        .ev-row:hover { background:var(--cream); }
        .ev-time { font-family:'IBM Plex Mono',monospace; font-size:0.8em; color:var(--forest); min-width:120px; }
        .ev-title { font-weight:500; flex:1; }
        .badge { font-family:'IBM Plex Mono',monospace; font-size:0.66em; text-transform:uppercase; letter-spacing:0.08em;
            padding:2px 7px; border-radius:5px; background:#eef3fb; color:var(--blue); }
        .badge.lead { background:#faf5e6; color:#8a6d1f; }
        .empty-day { color:var(--slate); font-style:italic; padding:8px 0; }
        /* modal */
        .overlay { position:fixed; inset:0; background:rgba(26,46,26,0.35); display:none; align-items:center; justify-content:center; padding:18px; z-index:50; }
        .overlay.open { display:flex; }
        .modal { background:var(--paper); border-radius:12px; box-shadow:0 24px 60px rgba(26,46,26,0.25);
            width:100%; max-width:460px; max-height:92vh; overflow-y:auto; padding:26px; }
        .modal h3 { font-family:'Playfair Display',Georgia,serif; font-size:1.3em; margin-bottom:18px; }
        .field { margin-bottom:14px; }
        .field label { display:block; font-family:'IBM Plex Mono',monospace; font-size:0.68em; text-transform:uppercase;
            letter-spacing:0.1em; color:var(--forest); margin-bottom:6px; }
        .field input, .field select, .field textarea { width:100%; padding:10px 12px; border:1px solid var(--sage);
            border-radius:7px; font-family:inherit; font-size:0.95em; color:var(--ink); background:var(--paper); }
        .field input:focus, .field select:focus, .field textarea:focus { outline:none; border-color:var(--forest); }
        .row2 { display:flex; gap:12px; } .row2 .field { flex:1; }
        .modal-actions { display:flex; gap:10px; margin-top:20px; align-items:center; }
        .modal-actions .spacer { flex:1; }
        .btn-danger { background:#fff; color:#9a3b2f; border-color:#e2c4be; }
        .btn-danger:hover { background:#9a3b2f; color:#fff; }
        .hidden { display:none; }
        @media (max-width:620px) {
            .cell { min-height:62px; } .ev { font-size:0.62em; }
            .nav .month-label { min-width:120px; font-size:1.05em; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">
            <div class="title-group">
                <h1>Calendar</h1>
                <div class="links"><a href="/">Home</a><a href="/chat">Chat</a><a href="/contacts">Contacts</a><a href="/visual">Visual Memory</a><a href="/documents">Documents</a></div>
            </div>
            <div class="nav">
                <button class="btn btn-icon" id="prev" aria-label="Previous month">&lsaquo;</button>
                <span class="month-label" id="monthLabel"></span>
                <button class="btn btn-icon" id="next" aria-label="Next month">&rsaquo;</button>
                <button class="btn" id="today">Today</button>
                <button class="btn btn-primary" id="add">+ New</button>
            </div>
        </div>

        <div class="grid">
            <div class="dow-row"><div>Mon</div><div>Tue</div><div>Wed</div><div>Thu</div><div>Fri</div><div>Sat</div><div>Sun</div></div>
            <div class="weeks" id="weeks"></div>
        </div>

        <div class="day-panel">
            <h2 id="dayHeading">Select a day</h2>
            <div id="dayEvents"></div>
            <button class="btn btn-primary" id="addForDay" style="margin-top:14px;">+ Add event</button>
        </div>
    </div>

    <div class="overlay" id="overlay">
        <div class="modal">
            <h3 id="modalTitle">New event</h3>
            <input type="hidden" id="fId">
            <div class="field">
                <label for="fTitle">Title</label>
                <input type="text" id="fTitle" placeholder="What is it?">
            </div>
            <div class="row2">
                <div class="field"><label for="fDate">Date</label><input type="date" id="fDate"></div>
                <div class="field"><label for="fStart">Start</label><input type="time" id="fStart"></div>
                <div class="field"><label for="fEnd">End</label><input type="time" id="fEnd"></div>
            </div>
            <div class="field">
                <label for="fRepeat">Repeat</label>
                <select id="fRepeat">
                    <option value="">Does not repeat</option>
                    <option value="daily">Daily</option>
                    <option value="weekly">Weekly</option>
                    <option value="weekdays">Every weekday (Mon-Fri)</option>
                    <option value="monthly">Monthly</option>
                    <option value="yearly">Yearly</option>
                    <option value="custom">Custom...</option>
                </select>
            </div>
            <div class="field hidden" id="customWrap">
                <label for="fCustom">Custom repeat</label>
                <input type="text" id="fCustom" placeholder="e.g. every 2 weeks, Mon/Wed/Fri, every 3 months">
            </div>
            <div class="field hidden" id="untilWrap">
                <label for="fUntil">Repeat until (optional)</label>
                <input type="date" id="fUntil">
            </div>
            <div class="field">
                <label for="fLead">Remind me</label>
                <select id="fLead">
                    <option value="0">At the time</option>
                    <option value="15">15 minutes before</option>
                    <option value="30">30 minutes before</option>
                    <option value="60">1 hour before</option>
                    <option value="120">2 hours before</option>
                    <option value="1440">1 day before</option>
                    <option value="10080">1 week before</option>
                </select>
            </div>
            <div class="field">
                <label for="fUser">For</label>
                <select id="fUser">
                    <option>Alex</option><option>Stella</option><option>Emmy</option>
                    <option>Athena</option><option>Vilda</option>
                </select>
            </div>
            <div class="field">
                <label for="fDesc">Notes</label>
                <textarea id="fDesc" rows="2" placeholder="Optional details"></textarea>
            </div>
            <div id="modalMsg" style="color:#9a3b2f;font-size:0.85em;"></div>
            <div class="modal-actions">
                <button class="btn btn-danger hidden" id="fDelete">Delete</button>
                <span class="spacer"></span>
                <button class="btn" id="fCancel">Cancel</button>
                <button class="btn btn-primary" id="fSave">Save</button>
            </div>
        </div>
    </div>

    <script>
    const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    let viewY, viewM, selected, events = [];

    function pad(n){ return (n<10?'0':'')+n; }
    function ymd(d){ return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate()); }
    function fmtTime(hm){ // 'HH:MM' -> '9:00 AM'
        if(!hm) return '';
        let [h,m] = hm.split(':').map(Number);
        const ap = h>=12?'PM':'AM'; h=h%12; if(h===0)h=12;
        return h+':'+pad(m)+' '+ap;
    }
    function esc(s){ const d=document.createElement('div'); d.textContent=s==null?'':String(s); return d.innerHTML; }

    // Monday-based weekday index (0=Mon..6=Sun)
    function mondayIdx(d){ return (d.getDay()+6)%7; }

    function gridRange(){
        const first = new Date(viewY, viewM, 1);
        const start = new Date(first); start.setDate(1 - mondayIdx(first));
        const end = new Date(start); end.setDate(start.getDate()+42); // 6 weeks
        return [start, end];
    }

    async function load(){
        const [start,end] = gridRange();
        const qs = 'start='+ymd(start)+'T00:00&end='+ymd(end)+'T00:00';
        try {
            const r = await fetch('/calendar/events?'+qs, {headers:{'Accept':'application/json'}});
            const data = await r.json();
            events = (data && data.events) ? data.events : [];
        } catch(e){ events = []; }
        renderGrid(); renderDay();
    }

    function eventsOn(dstr){
        return events.filter(e => (e.start||'').slice(0,10) === dstr)
                     .sort((a,b)=> (a.start||'').localeCompare(b.start||''));
    }

    function renderGrid(){
        document.getElementById('monthLabel').textContent = MONTHS[viewM]+' '+viewY;
        const [start] = gridRange();
        const todayStr = ymd(new Date());
        const weeks = document.getElementById('weeks');
        weeks.innerHTML = '';
        for(let i=0;i<42;i++){
            const d = new Date(start); d.setDate(start.getDate()+i);
            const dstr = ymd(d);
            const cell = document.createElement('div');
            cell.className = 'cell';
            if(d.getMonth()!==viewM) cell.className += ' other';
            if(dstr===todayStr) cell.className += ' today';
            if(dstr===selected) cell.className += ' selected';
            let html = '<div class="num">'+d.getDate()+'</div>';
            const evs = eventsOn(dstr);
            evs.slice(0,3).forEach(e=>{
                const t = e.start ? fmtTime(e.start.slice(11,16))+' ' : '';
                html += '<div class="ev'+(e.recurring?' rec':'')+'">'+t+esc(e.title)+'</div>';
            });
            if(evs.length>3) html += '<div class="more">+'+(evs.length-3)+' more</div>';
            cell.innerHTML = html;
            cell.addEventListener('click', ()=>{ selected=dstr; renderGrid(); renderDay(); });
            weeks.appendChild(cell);
        }
    }

    function renderDay(){
        const head = document.getElementById('dayHeading');
        const box = document.getElementById('dayEvents');
        if(!selected){ head.textContent='Select a day'; box.innerHTML=''; return; }
        const d = new Date(selected+'T00:00');
        head.textContent = d.toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric',year:'numeric'});
        const evs = eventsOn(selected);
        if(!evs.length){ box.innerHTML = '<div class="empty-day">Nothing scheduled.</div>'; return; }
        box.innerHTML = '';
        evs.forEach(e=>{
            const row = document.createElement('div');
            row.className = 'ev-row';
            let time = e.start ? fmtTime(e.start.slice(11,16)) : '';
            if(e.end) time += ' - '+fmtTime(e.end.slice(11,16));
            let badges = '';
            if(e.recurrence_human) badges += '<span class="badge">'+esc(e.recurrence_human)+'</span>';
            if(e.remind_before_min>0) badges += ' <span class="badge lead">remind '+leadText(e.remind_before_min)+' before</span>';
            row.innerHTML = '<span class="ev-time">'+esc(time||'all day')+'</span>'
                + '<span class="ev-title">'+esc(e.title)+'</span>'+badges;
            row.addEventListener('click', ()=> openModal(e));
            box.appendChild(row);
        });
    }

    function leadText(m){
        if(m%10080===0) return (m/10080)+' week'+(m/10080>1?'s':'');
        if(m%1440===0) return (m/1440)+' day'+(m/1440>1?'s':'');
        if(m%60===0) return (m/60)+' hour'+(m/60>1?'s':'');
        return m+' min';
    }

    // ----- modal -----
    const overlay = document.getElementById('overlay');
    function setRepeatUI(){
        const v = document.getElementById('fRepeat').value;
        document.getElementById('customWrap').classList.toggle('hidden', v!=='custom');
        document.getElementById('untilWrap').classList.toggle('hidden', v==='');
    }
    document.getElementById('fRepeat').addEventListener('change', setRepeatUI);

    function openModal(ev){
        document.getElementById('modalMsg').textContent='';
        if(ev){
            document.getElementById('modalTitle').textContent='Edit event';
            document.getElementById('fId').value = ev.id;
            document.getElementById('fTitle').value = ev.title||'';
            document.getElementById('fDate').value = (ev.start||'').slice(0,10);
            document.getElementById('fStart').value = (ev.start||'').slice(11,16);
            document.getElementById('fEnd').value = ev.end ? ev.end.slice(11,16) : '';
            document.getElementById('fDesc').value = ev.description||'';
            const rec = ev.recurrence||'';
            const presets = ['daily','weekly','weekdays','monthly','yearly'];
            if(rec===''){ document.getElementById('fRepeat').value=''; document.getElementById('fCustom').value=''; }
            else if(presets.includes(rec)){ document.getElementById('fRepeat').value=rec; document.getElementById('fCustom').value=''; }
            else { document.getElementById('fRepeat').value='custom'; document.getElementById('fCustom').value=ev.recurrence_human||rec; }
            document.getElementById('fLead').value = String(ev.remind_before_min||0);
            document.getElementById('fDelete').classList.remove('hidden');
        } else {
            document.getElementById('modalTitle').textContent='New event';
            document.getElementById('fId').value='';
            document.getElementById('fTitle').value='';
            document.getElementById('fDate').value = selected || ymd(new Date());
            document.getElementById('fStart').value='09:00';
            document.getElementById('fEnd').value='';
            document.getElementById('fDesc').value='';
            document.getElementById('fRepeat').value='';
            document.getElementById('fCustom').value='';
            document.getElementById('fUntil').value='';
            document.getElementById('fLead').value='0';
            document.getElementById('fDelete').classList.add('hidden');
        }
        setRepeatUI();
        overlay.classList.add('open');
    }
    function closeModal(){ overlay.classList.remove('open'); }

    document.getElementById('add').addEventListener('click', ()=>openModal(null));
    document.getElementById('addForDay').addEventListener('click', ()=>openModal(null));
    document.getElementById('fCancel').addEventListener('click', closeModal);
    overlay.addEventListener('click', e=>{ if(e.target===overlay) closeModal(); });

    function repeatValue(){
        const v = document.getElementById('fRepeat').value;
        if(v==='custom') return document.getElementById('fCustom').value.trim();
        return v;
    }

    document.getElementById('fSave').addEventListener('click', async ()=>{
        const id = document.getElementById('fId').value;
        const payload = {
            title: document.getElementById('fTitle').value.trim(),
            date: document.getElementById('fDate').value,
            start: document.getElementById('fStart').value,
            end: document.getElementById('fEnd').value,
            description: document.getElementById('fDesc').value,
            recurrence: repeatValue(),
            until: document.getElementById('fUntil').value,
            remind_before_min: parseInt(document.getElementById('fLead').value||'0',10),
            user: document.getElementById('fUser').value
        };
        if(!payload.title){ document.getElementById('modalMsg').textContent='Please enter a title.'; return; }
        if(!payload.date || !payload.start){ document.getElementById('modalMsg').textContent='Please set a date and start time.'; return; }
        const url = id ? '/calendar/event/update' : '/calendar/event';
        if(id) payload.id = parseInt(id,10);
        try {
            const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
            const data = await r.json();
            if(data && data.success===false){ document.getElementById('modalMsg').textContent = data.message||'Could not save.'; return; }
            selected = payload.date;
            closeModal(); load();
        } catch(e){ document.getElementById('modalMsg').textContent='Network error.'; }
    });

    document.getElementById('fDelete').addEventListener('click', async ()=>{
        const id = document.getElementById('fId').value;
        if(!id) return;
        if(!confirm('Delete this event? If it repeats, the whole series is removed.')) return;
        try {
            await fetch('/calendar/event/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id:parseInt(id,10)})});
            closeModal(); load();
        } catch(e){ document.getElementById('modalMsg').textContent='Network error.'; }
    });

    document.getElementById('prev').addEventListener('click', ()=>{ viewM--; if(viewM<0){viewM=11;viewY--;} load(); });
    document.getElementById('next').addEventListener('click', ()=>{ viewM++; if(viewM>11){viewM=0;viewY++;} load(); });
    document.getElementById('today').addEventListener('click', ()=>{ const n=new Date(); viewY=n.getFullYear(); viewM=n.getMonth(); selected=ymd(n); load(); });

    (function init(){ const n=new Date(); viewY=n.getFullYear(); viewM=n.getMonth(); selected=ymd(n); load(); })();
    </script>
</body>
</html>
"""
