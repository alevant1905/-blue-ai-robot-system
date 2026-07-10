"""Owner-facing continuity console for Blue-J. Pure template data."""


BLUEJ_CONTINUITY_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Blue-J Continuity</title>
    <link rel="stylesheet" href="/assets/blue.css">
    <script src="/assets/blue.js" defer></script>
    <style>
        :root {
            --bg:#f6f7f4; --paper:#fff; --ink:#17221c; --muted:#64706a;
            --line:#d8ded8; --blue:#2573c2; --green:#47735a; --amber:#a96f16;
            --red:#a9433d; --track:#e8ece8;
        }
        * { box-sizing:border-box; }
        body { margin:0; background:var(--bg); color:var(--ink); font-family:-apple-system,
               BlinkMacSystemFont,"Segoe UI",sans-serif; line-height:1.45; }
        button, input, textarea { font:inherit; }
        .shell { max-width:1120px; margin:0 auto; padding:32px 22px 56px; }
        header { display:flex; justify-content:space-between; align-items:flex-end; gap:18px;
                 border-bottom:1px solid var(--line); padding-bottom:18px; }
        h1 { margin:0; font-size:1.75rem; letter-spacing:0; }
        .meta { color:var(--muted); font-size:.86rem; margin-top:5px; }
        .links { display:flex; gap:14px; flex-wrap:wrap; }
        a { color:var(--blue); text-decoration:none; font-weight:600; }
        a:hover { text-decoration:underline; }
        section { padding:24px 0; border-bottom:1px solid var(--line); }
        .section-head { display:flex; justify-content:space-between; align-items:center;
                        gap:14px; margin-bottom:14px; }
        h2 { margin:0; font-size:1rem; text-transform:uppercase; letter-spacing:.08em; }
        .count { color:var(--muted); font-size:.82rem; font-variant-numeric:tabular-nums; }
        .workspace { background:var(--paper); border:1px solid var(--line); border-radius:8px;
                     overflow:hidden; }
        .ws-row { display:grid; grid-template-columns:minmax(150px,220px) 1fr; gap:18px;
                  padding:11px 14px; border-bottom:1px solid var(--line); }
        .ws-row:last-child { border-bottom:0; }
        .ws-key { color:var(--blue); font-size:.75rem; font-weight:700; text-transform:uppercase; }
        .ws-value { min-width:0; overflow-wrap:anywhere; }
        .drive-grid { display:grid; grid-template-columns:repeat(5,minmax(130px,1fr)); gap:12px; }
        .drive { min-width:0; }
        .drive-top { display:flex; justify-content:space-between; gap:8px; margin-bottom:6px;
                     font-size:.82rem; }
        .drive-name { font-weight:650; text-transform:capitalize; }
        .drive-value { color:var(--muted); font-variant-numeric:tabular-nums; }
        .drive-track { height:8px; background:var(--track); overflow:hidden; border-radius:4px; }
        .drive-fill { height:100%; background:var(--green); min-width:1px; }
        .drive-label { color:var(--muted); font-size:.72rem; margin-top:6px; min-height:2.2em; }
        .timeline { display:flex; flex-direction:column; gap:8px; }
        .episode { display:grid; grid-template-columns:92px minmax(0,1fr) auto; gap:14px;
                   align-items:start; background:var(--paper); border:1px solid var(--line);
                   border-radius:8px; padding:12px 12px 12px 14px; }
        .kind { display:inline-flex; align-items:center; justify-content:center; width:88px;
                min-height:25px; padding:3px 7px; border:1px solid var(--line); border-radius:4px;
                color:var(--muted); font-size:.68rem; font-weight:700; text-transform:uppercase; }
        .kind.perception { color:var(--blue); border-color:#b9d2eb; background:#f2f7fc; }
        .kind.action { color:var(--green); border-color:#bfd1c5; background:#f2f7f4; }
        .kind.correction { color:var(--amber); border-color:#e4c994; background:#fff8ea; }
        .kind.deletion { color:var(--red); border-color:#e4bdb9; background:#fff5f4; }
        .kind.reflection, .kind.idle { color:#69558f; border-color:#cfc3df; background:#f8f5fc; }
        .episode-summary { overflow-wrap:anywhere; }
        .episode-meta { color:var(--muted); font-size:.75rem; margin-top:5px; display:flex;
                        gap:10px; flex-wrap:wrap; }
        details { margin-top:8px; }
        summary { color:var(--blue); cursor:pointer; font-size:.76rem; }
        pre { max-height:260px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere;
              background:var(--bg); border:1px solid var(--line); border-radius:6px;
              padding:10px; font-size:.72rem; color:#34413a; }
        .episode-actions { display:flex; gap:4px; }
        .icon { width:34px; height:34px; display:inline-grid; place-items:center; border:1px solid var(--line);
                background:var(--paper); color:var(--muted); border-radius:6px; cursor:pointer; }
        .icon:hover { color:var(--ink); border-color:#aeb8b0; }
        .icon.danger:hover { color:var(--red); border-color:#d5aaa6; }
        .icon svg { width:17px; height:17px; fill:none; stroke:currentColor; stroke-width:1.8;
                    stroke-linecap:round; stroke-linejoin:round; }
        .button { border:1px solid var(--line); border-radius:6px; background:var(--paper); color:var(--ink);
                  padding:8px 12px; cursor:pointer; font-weight:600; }
        .button:hover { border-color:#aeb8b0; }
        .button.primary { color:#fff; background:var(--blue); border-color:var(--blue); }
        .button.danger { color:var(--red); border-color:#d5aaa6; }
        .empty { color:var(--muted); padding:20px 0; }
        .controls { display:flex; gap:10px; flex-wrap:wrap; }
        .status-error { color:var(--red); }
        .modal { position:fixed; inset:0; z-index:100; background:rgba(15,25,19,.48);
                 display:none; place-items:center; padding:18px; }
        .modal.open { display:grid; }
        .dialog { width:min(620px,100%); background:var(--paper); border:1px solid var(--line);
                  border-radius:8px; box-shadow:0 18px 55px rgba(0,0,0,.2); }
        .dialog-head { display:flex; align-items:center; justify-content:space-between; padding:15px 18px;
                       border-bottom:1px solid var(--line); }
        .dialog-head h3 { margin:0; font-size:1rem; }
        .dialog-body { padding:18px; }
        label { display:block; font-size:.78rem; font-weight:700; margin-bottom:6px; }
        textarea, input { width:100%; border:1px solid var(--line); border-radius:6px; padding:10px;
                          color:var(--ink); background:#fff; }
        textarea { min-height:120px; resize:vertical; }
        input { margin-bottom:14px; }
        textarea:focus, input:focus { outline:2px solid #c5ddf4; border-color:var(--blue); }
        .dialog-actions { display:flex; justify-content:flex-end; gap:8px; padding:0 18px 18px; }
        @media (max-width:850px) {
            .drive-grid { grid-template-columns:repeat(2,minmax(140px,1fr)); }
        }
        @media (max-width:620px) {
            .shell { padding:20px 14px 44px; }
            header { align-items:flex-start; flex-direction:column; }
            .ws-row { grid-template-columns:1fr; gap:4px; }
            .drive-grid { grid-template-columns:1fr; }
            .drive-label { min-height:0; }
            .episode { grid-template-columns:1fr auto; }
            .kind { grid-column:1; width:max-content; }
            .episode-main { grid-column:1 / -1; grid-row:2; }
            .episode-actions { grid-column:2; grid-row:1; }
        }
    </style>
</head>
<body>
<main class="shell">
    <header>
        <div>
            <h1>Blue-J Continuity</h1>
            <div class="meta" id="status">Loading state...</div>
        </div>
        <nav class="links"><a href="/bluej">Back to Blue-J</a><a href="/">Home</a></nav>
    </header>

    <section>
        <div class="section-head"><h2>Current Workspace</h2><span class="count" id="workspaceStamp"></span></div>
        <div class="workspace" id="workspace"></div>
    </section>

    <section>
        <div class="section-head"><h2>Attentional State</h2><span class="count">bounded 0.00-1.00</span></div>
        <div class="drive-grid" id="drives"></div>
    </section>

    <section>
        <div class="section-head"><h2>Episode Journal</h2><span class="count" id="episodeCount"></span></div>
        <div class="timeline" id="timeline"></div>
        <button class="button" id="olderBtn" type="button" style="margin-top:12px;display:none">Load older</button>
    </section>

    <section>
        <div class="section-head"><h2>Continuity Store</h2></div>
        <div class="controls">
            <button class="button" id="archiveReset" type="button">Archive and reset</button>
            <button class="button danger" id="wipeReset" type="button">Wipe and reset</button>
        </div>
    </section>
</main>

<div class="modal" id="editModal" role="dialog" aria-modal="true" aria-labelledby="editTitle">
    <form class="dialog" id="editForm">
        <div class="dialog-head">
            <h3 id="editTitle">Correct Episode</h3>
            <button class="icon" id="editClose" type="button" aria-label="Close" title="Close">
                <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>
            </button>
        </div>
        <div class="dialog-body">
            <label for="replacement">Replacement</label>
            <textarea id="replacement" required></textarea>
            <label for="reason">Reason</label>
            <input id="reason" type="text" maxlength="500">
        </div>
        <div class="dialog-actions">
            <button class="button" id="editCancel" type="button">Cancel</button>
            <button class="button primary" type="submit">Save correction</button>
        </div>
    </form>
</div>

<script>
(function () {
    'use strict';
    var state = null;
    var oldestSeq = null;
    var editingId = null;
    var timeline = document.getElementById('timeline');

    function text(tag, value, cls) {
        var el = document.createElement(tag);
        if (cls) el.className = cls;
        el.textContent = value == null ? '' : String(value);
        return el;
    }

    function fmtTime(value) {
        var d = new Date(value || '');
        if (isNaN(d.getTime())) return String(value || '?');
        return d.toLocaleString([], {year:'numeric', month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});
    }

    function renderWorkspace(data) {
        var box = document.getElementById('workspace');
        box.textContent = '';
        String(data.workspace || '').split('\n').forEach(function (line) {
            line = line.trim();
            if (!line) return;
            var match = /^([A-Z][A-Z -]+):\s*(.*)$/.exec(line);
            var row = document.createElement('div'); row.className = 'ws-row';
            row.appendChild(text('div', match ? match[1] : 'State', 'ws-key'));
            row.appendChild(text('div', match ? match[2] : line, 'ws-value'));
            box.appendChild(row);
        });
        document.getElementById('workspaceStamp').textContent =
            fmtTime(data.updated) + ' | ' + Number(data.passes || 0) + ' passes';
    }

    function renderDrives(drives) {
        var box = document.getElementById('drives'); box.textContent = '';
        (drives || []).forEach(function (drive) {
            var item = document.createElement('div'); item.className = 'drive';
            var top = document.createElement('div'); top.className = 'drive-top';
            top.appendChild(text('span', drive.name, 'drive-name'));
            top.appendChild(text('span', Number(drive.value || 0).toFixed(2), 'drive-value'));
            var track = document.createElement('div'); track.className = 'drive-track';
            var fill = document.createElement('div'); fill.className = 'drive-fill';
            fill.style.width = Math.max(0, Math.min(100, Number(drive.value || 0) * 100)) + '%';
            track.appendChild(fill); item.appendChild(top); item.appendChild(track);
            item.appendChild(text('div', drive.label, 'drive-label')); box.appendChild(item);
        });
    }

    function iconButton(label, path, cls) {
        var button = document.createElement('button');
        button.type = 'button'; button.className = 'icon' + (cls ? ' ' + cls : '');
        button.setAttribute('aria-label', label); button.title = label;
        button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + path + '</svg>';
        return button;
    }

    function episodeNode(item) {
        var row = document.createElement('article'); row.className = 'episode';
        row.dataset.id = item.id;
        row.appendChild(text('span', item.kind || 'episode', 'kind ' + (item.kind || '')));
        var main = document.createElement('div'); main.className = 'episode-main';
        main.appendChild(text('div', item.summary || '(empty)', 'episode-summary'));
        var meta = document.createElement('div'); meta.className = 'episode-meta';
        meta.appendChild(text('span', fmtTime(item.occurred_at)));
        meta.appendChild(text('span', item.source || 'unknown'));
        meta.appendChild(text('span', 'salience ' + Number(item.salience || 0).toFixed(2)));
        main.appendChild(meta);
        if (item.details && Object.keys(item.details).length) {
            var details = document.createElement('details');
            details.appendChild(text('summary', 'Structured record'));
            details.appendChild(text('pre', JSON.stringify(item.details, null, 2)));
            main.appendChild(details);
        }
        row.appendChild(main);
        var actions = document.createElement('div'); actions.className = 'episode-actions';
        var edit = iconButton('Correct episode', '<path d="M4 20h4l11-11-4-4L4 16v4zM13.5 6.5l4 4"/>');
        edit.addEventListener('click', function () { openEdit(item); });
        var remove = iconButton('Delete episode', '<path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/>', 'danger');
        remove.addEventListener('click', function () { deleteEpisode(item); });
        actions.appendChild(edit); actions.appendChild(remove); row.appendChild(actions);
        return row;
    }

    function renderEpisodes(items, append) {
        if (!append) timeline.textContent = '';
        (items || []).forEach(function (item) { timeline.appendChild(episodeNode(item)); });
        if (!timeline.children.length) timeline.appendChild(text('div', 'No episodes yet.', 'empty'));
        if (items && items.length) oldestSeq = items[items.length - 1].seq;
        document.getElementById('olderBtn').style.display = (items && items.length >= 24) ? '' : 'none';
    }

    function render(data) {
        state = data;
        renderWorkspace(data); renderDrives(data.drives); renderEpisodes(data.episodes, false);
        var stats = data.stats || {};
        document.getElementById('episodeCount').textContent = Number(stats.episodes || 0) + ' total';
        document.getElementById('status').className = 'meta';
        document.getElementById('status').textContent =
            Number(stats.pending_reflections || 0) + ' queued | ' +
            Number(data.ruminations_left || 0) + ' idle passes remaining';
    }

    async function loadState() {
        try {
            var response = await fetch('/bluej/state', {cache:'no-store'});
            var data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || 'State request failed');
            render(data);
        } catch (error) {
            var status = document.getElementById('status');
            status.className = 'meta status-error'; status.textContent = error.message;
        }
    }

    async function loadOlder() {
        if (oldestSeq == null) return;
        var response = await fetch('/bluej/episodes?limit=24&before=' + encodeURIComponent(oldestSeq));
        var data = await response.json();
        if (response.ok && data.ok) renderEpisodes(data.episodes || [], true);
    }

    function openEdit(item) {
        editingId = item.id;
        document.getElementById('replacement').value = item.summary || '';
        document.getElementById('reason').value = '';
        document.getElementById('editModal').classList.add('open');
        document.getElementById('replacement').focus();
    }

    function closeEdit() {
        editingId = null; document.getElementById('editModal').classList.remove('open');
    }

    async function submitEdit(event) {
        event.preventDefault(); if (!editingId) return;
        var replacement = document.getElementById('replacement').value.trim();
        var reason = document.getElementById('reason').value.trim();
        if (!replacement) return;
        var response = await fetch('/bluej/episodes/' + encodeURIComponent(editingId) + '/correct', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({replacement:replacement, reason:reason})
        });
        var data = await response.json();
        if (!response.ok || !data.ok) { alert(data.error || 'Correction failed'); return; }
        closeEdit(); await loadState();
    }

    async function deleteEpisode(item) {
        if (!confirm('Delete this episode from Blue-J continuity?')) return;
        var response = await fetch('/bluej/episodes/' + encodeURIComponent(item.id), {
            method:'DELETE', headers:{'Content-Type':'application/json'}, body:'{}'
        });
        var data = await response.json();
        if (!response.ok || !data.ok) { alert(data.error || 'Delete failed'); return; }
        await loadState();
    }

    async function resetStore(archive) {
        var prompt = archive
            ? 'Archive the current continuity database and start a new one?'
            : 'Permanently wipe the continuity database and start a new one?';
        if (!confirm(prompt)) return;
        var response = await fetch('/bluej/reset', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({archive:archive})
        });
        var data = await response.json();
        if (!response.ok || !data.ok) { alert(data.error || 'Reset failed'); return; }
        await loadState();
    }

    document.getElementById('olderBtn').addEventListener('click', loadOlder);
    document.getElementById('editForm').addEventListener('submit', submitEdit);
    document.getElementById('editClose').addEventListener('click', closeEdit);
    document.getElementById('editCancel').addEventListener('click', closeEdit);
    document.getElementById('editModal').addEventListener('click', function (event) {
        if (event.target === this) closeEdit();
    });
    document.addEventListener('keydown', function (event) { if (event.key === 'Escape') closeEdit(); });
    document.getElementById('archiveReset').addEventListener('click', function () { resetStore(true); });
    document.getElementById('wipeReset').addEventListener('click', function () { resetStore(false); });
    loadState(); setInterval(loadState, 10000);
}());
</script>
</body>
</html>"""

