"""Extracted verbatim from bluetools.py (see blue/server/pages).

Do not import bluetools here; this module is pure data.
"""

VISUAL_HTML = r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Visual Memory - Blue</title>
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
        .wrap { max-width:920px; margin:0 auto; }
        .topbar { display:flex; align-items:flex-end; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-bottom:16px; }
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
        .tabs { display:flex; gap:8px; margin-bottom:18px; }
        .tab { border:1px solid var(--line); background:var(--paper); border-radius:8px; padding:8px 18px;
               font-weight:500; color:var(--slate); }
        .tab.active { background:var(--ink); color:#fff; border-color:var(--ink); }
        .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:16px; }
        .card { background:var(--paper); border:1px solid var(--line); border-radius:12px; box-shadow:var(--shadow);
                overflow:hidden; cursor:pointer; transition:border-color .15s,box-shadow .15s; }
        .card:hover { border-color:var(--sage); box-shadow:0 10px 28px rgba(26,46,26,0.10); }
        .photo { width:100%; height:150px; background:#eef2ec; display:flex; align-items:center; justify-content:center;
                 color:var(--sage); overflow:hidden; }
        .photo img { width:100%; height:100%; object-fit:cover; display:block; }
        .photo svg { width:40px; height:40px; fill:none; stroke:currentColor; stroke-width:1.3; }
        .card-body { padding:12px 14px; }
        .card-name { font-weight:600; }
        .card-sub { font-size:0.82em; color:var(--slate); margin-top:2px;
                    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .empty { color:var(--slate); text-align:center; padding:48px 20px; font-style:italic; grid-column:1/-1; }
        .empty .big { font-family:'Playfair Display',Georgia,serif; font-size:1.2em; color:var(--ink); font-style:normal; margin-bottom:6px; }
        .overlay { position:fixed; inset:0; background:rgba(26,46,26,0.35); display:none; align-items:center; justify-content:center; padding:18px; z-index:50; }
        .overlay.open { display:flex; }
        .modal { background:var(--paper); border-radius:12px; box-shadow:0 24px 60px rgba(26,46,26,0.25);
            width:100%; max-width:460px; max-height:92vh; overflow-y:auto; padding:24px; }
        .modal h3 { font-family:'Playfair Display',Georgia,serif; font-size:1.3em; margin-bottom:16px; }
        .photo-edit { display:flex; gap:14px; align-items:center; margin-bottom:16px; }
        .photo-edit .thumb { width:84px; height:84px; border-radius:10px; background:#eef2ec; overflow:hidden;
            display:flex; align-items:center; justify-content:center; flex:none; color:var(--sage); }
        .photo-edit .thumb img { width:100%; height:100%; object-fit:cover; }
        .photo-edit .thumb svg { width:30px; height:30px; fill:none; stroke:currentColor; stroke-width:1.4; }
        .field { margin-bottom:13px; }
        .field label { display:block; font-family:'IBM Plex Mono',monospace; font-size:0.66em; text-transform:uppercase;
            letter-spacing:0.1em; color:var(--forest); margin-bottom:6px; }
        .field input, .field textarea { width:100%; padding:10px 12px; border:1px solid var(--sage);
            border-radius:7px; font-family:inherit; font-size:0.95em; color:var(--ink); background:var(--paper); }
        .field input:focus, .field textarea:focus { outline:none; border-color:var(--forest); }
        .modal-actions { display:flex; gap:10px; margin-top:18px; align-items:center; }
        .modal-actions .spacer { flex:1; }
        .btn-danger { background:#fff; color:#9a3b2f; border-color:#e2c4be; }
        .btn-danger:hover { background:#9a3b2f; color:#fff; }
        .hidden { display:none; }
        .msg { font-size:0.85em; margin-top:6px; }
        .msg.err { color:#9a3b2f; } .msg.ok { color:#2e4a2e; }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">
            <div class="title-group">
                <h1>Visual Memory</h1>
                <div class="links"><a href="/">Home</a><a href="/chat">Chat</a><a href="/contacts">Contacts</a><a href="/calendar">Calendar</a></div>
            </div>
            <button class="btn btn-primary" id="add">+ New</button>
        </div>
        <div class="tabs">
            <button class="tab active" data-type="person">People</button>
            <button class="tab" data-type="place">Places</button>
            <button class="tab" data-type="object">Things</button>
        </div>
        <div class="grid" id="grid"></div>
    </div>

    <div class="overlay" id="overlay">
        <div class="modal">
            <h3 id="modalTitle">New</h3>
            <input type="hidden" id="fId">
            <div class="photo-edit">
                <div class="thumb" id="thumb"></div>
                <div>
                    <input type="file" id="photoInput" accept="image/*" style="display:none">
                    <button class="btn" id="uploadBtn" type="button">Upload photo</button>
                    <button class="btn" id="captureBtn" type="button" title="Capture from Blue's camera">Use Blue's camera</button>
                    <div class="msg" id="photoMsg"></div>
                </div>
            </div>
            <div class="field"><label for="fName">Name</label><input type="text" id="fName"></div>
            <div id="fields"></div>
            <div id="modalMsg" class="msg err"></div>
            <div class="modal-actions">
                <button class="btn btn-danger hidden" id="fDelete">Delete</button>
                <span class="spacer"></span>
                <button class="btn" id="fCancel">Cancel</button>
                <button class="btn btn-primary" id="fSave">Save</button>
            </div>
        </div>
    </div>

    <script>
    const SCHEMA = {
        person: [['relationship','Relationship'],['typical_appearance','Appearance'],['description','About them'],['common_locations','Usually found'],['notes','Notes']],
        place:  [['description','About'],['typical_contents','Typically contains'],['typical_lighting','Lighting'],['notes','Notes']],
        object: [['category','Category'],['description','About'],['typical_location','Usually kept'],['notes','Notes']]
    };
    const PERSON_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 4-6 8-6s8 2 8 6"/></svg>';
    let curType='person', items=[];
    function esc(s){ const d=document.createElement('div'); d.textContent=s==null?'':String(s); return d.innerHTML; }
    function imgUrl(it){ return '/visual/image?type='+curType+'&id='+it.id+'&t='+(it._t||0); }

    async function load(){
        try {
            const r=await fetch('/visual/list?type='+curType,{headers:{'Accept':'application/json'}});
            const data=await r.json(); items=(data&&data.items)?data.items:[];
        } catch(e){ items=[]; }
        render();
    }
    function subLine(it){
        if(curType==='person') return it.relationship||it.typical_appearance||it.description||'';
        if(curType==='object') return it.category||it.description||'';
        return it.description||it.typical_contents||'';
    }
    function render(){
        const g=document.getElementById('grid');
        if(!items.length){ g.innerHTML='<div class="empty"><div class="big">Nobody here yet</div>Add someone with + New, give them a photo, and Blue can start recognizing them.</div>'; return; }
        g.innerHTML='';
        items.forEach(it=>{
            const card=document.createElement('div'); card.className='card';
            const photo = it.has_image ? '<img src="'+imgUrl(it)+'" alt="">' : PERSON_SVG;
            card.innerHTML='<div class="photo">'+photo+'</div><div class="card-body"><div class="card-name">'+esc(it.name)+'</div><div class="card-sub">'+esc(subLine(it))+'</div></div>';
            card.addEventListener('click',()=>openModal(it));
            g.appendChild(card);
        });
    }

    const overlay=document.getElementById('overlay');
    function buildFields(it){
        const box=document.getElementById('fields'); box.innerHTML='';
        SCHEMA[curType].forEach(([key,label])=>{
            const wrap=document.createElement('div'); wrap.className='field';
            const big = (key==='description'||key==='notes');
            wrap.innerHTML='<label>'+label+'</label>'+(big?'<textarea rows="2" data-k="'+key+'"></textarea>':'<input type="text" data-k="'+key+'">');
            box.appendChild(wrap);
            box.querySelector('[data-k="'+key+'"]').value = it ? (it[key]||'') : '';
        });
    }
    function setThumb(it){
        const t=document.getElementById('thumb');
        t.innerHTML = (it&&it.has_image) ? '<img src="'+imgUrl(it)+'">' : PERSON_SVG;
    }
    function openModal(it){
        document.getElementById('modalMsg').textContent='';
        document.getElementById('photoMsg').textContent='';
        document.getElementById('modalTitle').textContent = it ? ('Edit '+curType) : ('New '+curType);
        document.getElementById('fId').value = it?it.id:'';
        document.getElementById('fName').value = it?it.name:'';
        buildFields(it); setThumb(it);
        document.getElementById('fDelete').classList.toggle('hidden', !it);
        document.getElementById('captureBtn').classList.toggle('hidden', !it); // need an id to attach a photo
        document.getElementById('uploadBtn').classList.toggle('hidden', !it);
        overlay.classList.add('open');
        document.getElementById('fName').focus();
    }
    function closeModal(){ overlay.classList.remove('open'); }

    document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>{
        document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
        t.classList.add('active'); curType=t.dataset.type; load();
    }));
    document.getElementById('add').addEventListener('click',()=>openModal(null));
    document.getElementById('fCancel').addEventListener('click',closeModal);
    overlay.addEventListener('click',e=>{ if(e.target===overlay) closeModal(); });

    function collect(){
        const payload={type:curType, name:document.getElementById('fName').value.trim()};
        document.querySelectorAll('#fields [data-k]').forEach(el=>{ payload[el.dataset.k]=el.value.trim(); });
        return payload;
    }
    document.getElementById('fSave').addEventListener('click', async ()=>{
        const id=document.getElementById('fId').value;
        const payload=collect();
        if(!payload.name){ document.getElementById('modalMsg').textContent='Please enter a name.'; return; }
        const url=id?'/visual/entity/update':'/visual/entity';
        if(id) payload.id=parseInt(id,10);
        try {
            const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
            const data=await r.json();
            if(data&&data.success===false){ document.getElementById('modalMsg').textContent=data.message||'Could not save.'; return; }
            if(!id){ // reopen the newly created one so a photo can be attached
                const newId = data.id;
                await load();
                const fresh = items.find(x=>x.id===newId);
                if(fresh){ openModal(fresh); return; }
            }
            closeModal(); load();
        } catch(e){ document.getElementById('modalMsg').textContent='Network error.'; }
    });
    document.getElementById('fDelete').addEventListener('click', async ()=>{
        const id=document.getElementById('fId').value; if(!id) return;
        if(!confirm('Delete this from Blue\'s memory?')) return;
        await fetch('/visual/entity/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:curType,id:parseInt(id,10)})});
        closeModal(); load();
    });

    document.getElementById('uploadBtn').addEventListener('click',()=>document.getElementById('photoInput').click());
    document.getElementById('photoInput').addEventListener('change', async ()=>{
        const id=document.getElementById('fId').value; if(!id || !photoInput.files.length) return;
        const fd=new FormData(); fd.append('type',curType); fd.append('id',id); fd.append('file',photoInput.files[0]);
        photoInput.value='';
        document.getElementById('photoMsg').textContent='Uploading...';
        try {
            const r=await fetch('/visual/image',{method:'POST',body:fd}); const data=await r.json();
            if(data&&data.success){ const m=document.getElementById('photoMsg');
                if(data.warning){ m.className='msg err'; m.textContent=data.warning; }
                else { m.className='msg ok'; m.textContent=data.face_found?'Photo saved — face detected, ready to recognize.':'Photo saved.'; }
                const it=items.find(x=>x.id===parseInt(id,10)); if(it){ it.has_image=true; it._t=Date.now(); setThumb(it);} load();
            } else { document.getElementById('photoMsg').className='msg err'; document.getElementById('photoMsg').textContent=(data&&data.message)||'Upload failed.'; }
        } catch(e){ document.getElementById('photoMsg').className='msg err'; document.getElementById('photoMsg').textContent='Upload failed.'; }
    });
    document.getElementById('captureBtn').addEventListener('click', async ()=>{
        const id=document.getElementById('fId').value; if(!id) return;
        document.getElementById('photoMsg').className='msg'; document.getElementById('photoMsg').textContent='Capturing from camera...';
        try {
            const r=await fetch('/visual/capture',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:curType,id:parseInt(id,10)})});
            const data=await r.json();
            if(data&&data.success){ const m=document.getElementById('photoMsg');
                if(data.warning){ m.className='msg err'; m.textContent=data.warning; }
                else { m.className='msg ok'; m.textContent=data.face_found?'Captured — face detected, ready to recognize.':'Captured.'; }
                const it=items.find(x=>x.id===parseInt(id,10)); if(it){ it.has_image=true; it._t=Date.now(); setThumb(it);} load();
            } else { document.getElementById('photoMsg').className='msg err'; document.getElementById('photoMsg').textContent=(data&&data.message)||'Camera unavailable.'; }
        } catch(e){ document.getElementById('photoMsg').className='msg err'; document.getElementById('photoMsg').textContent='Camera error.'; }
    });

    load();
    </script>
</body>
</html>
"""
