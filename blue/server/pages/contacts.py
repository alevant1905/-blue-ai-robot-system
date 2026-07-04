"""Extracted verbatim from bluetools.py (see blue/server/pages).

Do not import bluetools here; this module is pure data.
"""

CONTACTS_HTML = r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Contacts - Blue</title>
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
        .wrap { max-width:880px; margin:0 auto; }
        .ic { width:1em; height:1em; vertical-align:-0.12em; margin-right:.4em; fill:none;
              stroke:currentColor; stroke-width:1.7; stroke-linecap:round; stroke-linejoin:round; flex:none; }
        .topbar { display:flex; align-items:flex-end; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-bottom:18px; }
        .title-group::before { content:""; display:block; width:56px; height:3px;
            background:linear-gradient(90deg,var(--gold),var(--blue)); margin-bottom:12px; }
        .title-group h1 { font-family:'Playfair Display',Georgia,serif; font-weight:700; font-size:1.8em; letter-spacing:-0.01em; }
        .title-group .links { margin-top:4px; }
        .title-group .links a { color:var(--forest); text-decoration:none; font-weight:500; margin-right:16px; font-size:0.9em; }
        .title-group .links a:hover { color:var(--ink); text-decoration:underline; }
        button { font-family:inherit; cursor:pointer; }
        .btn { border:1px solid var(--sage); background:var(--paper); color:var(--forest);
               border-radius:8px; padding:9px 14px; font-size:0.9em; font-weight:500; transition:background .2s,border-color .2s; }
        .btn:hover { background:var(--cream); border-color:var(--forest); }
        .btn-primary { background:var(--ink); color:#fff; border-color:var(--ink); }
        .btn-primary:hover { background:var(--forest); border-color:var(--forest); }
        .toolbar { display:flex; gap:10px; margin-bottom:16px; }
        .toolbar input { flex:1; padding:10px 14px; border:1px solid var(--sage); border-radius:8px;
            font-family:inherit; font-size:0.95em; color:var(--ink); background:var(--paper); }
        .toolbar input:focus { outline:none; border-color:var(--forest); }
        .card { background:var(--paper); border:1px solid var(--line); border-radius:12px; box-shadow:var(--shadow); overflow:hidden; }
        .contact { display:flex; align-items:center; gap:14px; padding:14px 18px; border-bottom:1px solid var(--line); cursor:pointer; }
        .contact:last-child { border-bottom:none; }
        .contact:hover { background:var(--cream); }
        .avatar { width:40px; height:40px; border-radius:50%; background:#eef2ec; color:var(--forest);
            display:flex; align-items:center; justify-content:center; font-weight:600; flex:none;
            font-family:'IBM Plex Mono',monospace; font-size:0.9em; }
        .c-main { flex:1; min-width:0; }
        .c-name { font-weight:600; }
        .c-sub { font-family:'IBM Plex Mono',monospace; font-size:0.78em; color:var(--slate);
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .c-rel { font-family:'IBM Plex Mono',monospace; font-size:0.66em; text-transform:uppercase; letter-spacing:0.08em;
            color:var(--blue); background:#eef3fb; padding:2px 8px; border-radius:5px; flex:none; }
        .empty { color:var(--slate); text-align:center; padding:48px 20px; font-style:italic; }
        .empty .big { font-family:'Playfair Display',Georgia,serif; font-size:1.2em; color:var(--ink); font-style:normal; margin-bottom:6px; }
        .overlay { position:fixed; inset:0; background:rgba(26,46,26,0.35); display:none; align-items:center; justify-content:center; padding:18px; z-index:50; }
        .overlay.open { display:flex; }
        .modal { background:var(--paper); border-radius:12px; box-shadow:0 24px 60px rgba(26,46,26,0.25);
            width:100%; max-width:440px; max-height:92vh; overflow-y:auto; padding:26px; }
        .modal h3 { font-family:'Playfair Display',Georgia,serif; font-size:1.3em; margin-bottom:18px; }
        .field { margin-bottom:14px; }
        .field label { display:block; font-family:'IBM Plex Mono',monospace; font-size:0.68em; text-transform:uppercase;
            letter-spacing:0.1em; color:var(--forest); margin-bottom:6px; }
        .field input, .field textarea { width:100%; padding:10px 12px; border:1px solid var(--sage);
            border-radius:7px; font-family:inherit; font-size:0.95em; color:var(--ink); background:var(--paper); }
        .field input:focus, .field textarea:focus { outline:none; border-color:var(--forest); }
        .modal-actions { display:flex; gap:10px; margin-top:20px; align-items:center; }
        .modal-actions .spacer { flex:1; }
        .btn-danger { background:#fff; color:#9a3b2f; border-color:#e2c4be; }
        .btn-danger:hover { background:#9a3b2f; color:#fff; }
        .hidden { display:none; }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">
            <div class="title-group">
                <h1>Contacts</h1>
                <div class="links"><a href="/">Home</a><a href="/chat">Chat</a><a href="/calendar">Calendar</a><a href="/visual">Visual Memory</a><a href="/documents">Documents</a></div>
            </div>
            <button class="btn btn-primary" id="add">+ New contact</button>
        </div>
        <div class="toolbar">
            <input type="search" id="search" placeholder="Search by name, email, or relationship...">
        </div>
        <div class="card" id="list"></div>
    </div>

    <div class="overlay" id="overlay">
        <div class="modal">
            <h3 id="modalTitle">New contact</h3>
            <input type="hidden" id="fId">
            <div class="field"><label for="fName">Name</label><input type="text" id="fName" placeholder="Full name"></div>
            <div class="field"><label for="fEmail">Email</label><input type="email" id="fEmail" placeholder="name@example.com"></div>
            <div class="field"><label for="fPhone">Phone</label><input type="text" id="fPhone" placeholder="Optional"></div>
            <div class="field"><label for="fRel">Relationship</label><input type="text" id="fRel" placeholder="e.g. wife, colleague, doctor"></div>
            <div class="field"><label for="fNotes">Notes</label><textarea id="fNotes" rows="2" placeholder="Optional"></textarea></div>
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
    let contacts = [];
    function esc(s){ const d=document.createElement('div'); d.textContent=s==null?'':String(s); return d.innerHTML; }
    function initials(name){
        const parts=(name||'').trim().split(/\s+/);
        return ((parts[0]||'')[0]||'') + ((parts[1]||'')[0]||'');
    }

    async function load(){
        const q = document.getElementById('search').value.trim();
        try {
            const r = await fetch('/contacts/list?q='+encodeURIComponent(q), {headers:{'Accept':'application/json'}});
            const data = await r.json();
            contacts = (data && data.contacts) ? data.contacts : [];
        } catch(e){ contacts = []; }
        render();
    }

    function render(){
        const box = document.getElementById('list');
        if(!contacts.length){
            box.innerHTML = '<div class="empty"><div class="big">No contacts yet</div>Add someone with the button above, or just tell Blue in chat.</div>';
            return;
        }
        box.innerHTML = '';
        contacts.forEach(c=>{
            const row = document.createElement('div');
            row.className = 'contact';
            let sub = esc(c.email||'');
            if(c.phone) sub += (sub?'  &middot;  ':'')+esc(c.phone);
            row.innerHTML = '<div class="avatar">'+esc(initials(c.name).toUpperCase())+'</div>'
                + '<div class="c-main"><div class="c-name">'+esc(c.name)+'</div>'
                + (sub?'<div class="c-sub">'+sub+'</div>':'')+'</div>'
                + (c.relationship?'<span class="c-rel">'+esc(c.relationship)+'</span>':'');
            row.addEventListener('click', ()=>openModal(c));
            box.appendChild(row);
        });
    }

    const overlay = document.getElementById('overlay');
    function openModal(c){
        document.getElementById('modalMsg').textContent='';
        if(c){
            document.getElementById('modalTitle').textContent='Edit contact';
            document.getElementById('fId').value=c.id;
            document.getElementById('fName').value=c.name||'';
            document.getElementById('fEmail').value=c.email||'';
            document.getElementById('fPhone').value=c.phone||'';
            document.getElementById('fRel').value=c.relationship||'';
            document.getElementById('fNotes').value=c.notes||'';
            document.getElementById('fDelete').classList.remove('hidden');
        } else {
            document.getElementById('modalTitle').textContent='New contact';
            ['fId','fName','fEmail','fPhone','fRel','fNotes'].forEach(id=>document.getElementById(id).value='');
            document.getElementById('fDelete').classList.add('hidden');
        }
        overlay.classList.add('open');
        document.getElementById('fName').focus();
    }
    function closeModal(){ overlay.classList.remove('open'); }

    document.getElementById('add').addEventListener('click', ()=>openModal(null));
    document.getElementById('fCancel').addEventListener('click', closeModal);
    overlay.addEventListener('click', e=>{ if(e.target===overlay) closeModal(); });
    let t; document.getElementById('search').addEventListener('input', ()=>{ clearTimeout(t); t=setTimeout(load,200); });

    document.getElementById('fSave').addEventListener('click', async ()=>{
        const id=document.getElementById('fId').value;
        const payload={
            name:document.getElementById('fName').value.trim(),
            email:document.getElementById('fEmail').value.trim(),
            phone:document.getElementById('fPhone').value.trim(),
            relationship:document.getElementById('fRel').value.trim(),
            notes:document.getElementById('fNotes').value.trim()
        };
        if(!payload.name){ document.getElementById('modalMsg').textContent='Please enter a name.'; return; }
        const url = id ? '/contacts/update' : '/contacts';
        if(id) payload.id=parseInt(id,10);
        try {
            const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
            const data=await r.json();
            if(data && data.success===false){ document.getElementById('modalMsg').textContent=data.message||'Could not save.'; return; }
            closeModal(); load();
        } catch(e){ document.getElementById('modalMsg').textContent='Network error.'; }
    });

    document.getElementById('fDelete').addEventListener('click', async ()=>{
        const id=document.getElementById('fId').value;
        if(!id) return;
        if(!confirm('Delete this contact?')) return;
        try {
            await fetch('/contacts/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:parseInt(id,10)})});
            closeModal(); load();
        } catch(e){ document.getElementById('modalMsg').textContent='Network error.'; }
    });

    load();
    </script>
</body>
</html>
"""
