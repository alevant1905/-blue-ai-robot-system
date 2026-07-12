"""Extracted verbatim from bluetools.py (see blue/server/pages).

Do not import bluetools here; this module is pure data.
"""

HEAD_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ head_robot_name }}'s Head — Tuning</title>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400&family=Playfair+Display:wght@600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/assets/blue.css">
    <script src="/assets/blue.js" defer></script>
    <style>
        :root { --cream:#faf8f4; --paper:#fff; --ink:#1a2e1a; --forest:#4a6b4a; --sage:#8fae8f; --slate:#64748b; --line:rgba(143,174,143,0.32); --shadow:0 8px 24px rgba(26,46,26,0.06); }
        * { box-sizing:border-box; margin:0; padding:0; }
        body { font-family:'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:var(--cream); color:var(--ink); line-height:1.5; padding:22px 18px 60px; }
        .wrap { max-width: 820px; margin: 0 auto; }
        .head { display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; flex-wrap:wrap; gap:8px; }
        .head h1 { font-family:'Playfair Display', Georgia, serif; font-weight:700; font-size:1.7em; }
        .head a { color:var(--forest); text-decoration:none; font-size:0.95em; }
        .status { display:inline-block; padding:5px 14px; border-radius:20px; font-size:0.85em; font-weight:500; }
        .status.on { background:#e0f0e0; color:#2d6b2d; }
        .status.off { background:#f4e0e0; color:#7a2e22; }
        .card { background:var(--paper); border:1px solid var(--line); border-radius:12px; box-shadow:var(--shadow); padding:18px 20px; margin-bottom:14px; }
        .card h2 { font-family:'Playfair Display', Georgia, serif; font-size:1.1em; font-weight:600; margin-bottom:6px; color:var(--forest); }
        .card .sub { font-size:0.85em; color:var(--slate); margin-bottom:10px; }
        .row { display:grid; grid-template-columns: 110px 1fr 56px 140px; gap:10px; align-items:center; padding:7px 0; border-bottom:1px dashed var(--line); }
        .row:last-child { border-bottom:none; }
        .row .name { font-weight:500; }
        .row input[type=range] { width:100%; accent-color:var(--forest); }
        .row .val { font-family:'IBM Plex Mono', monospace; text-align:right; font-size:0.9em; color:var(--slate); }
        .btn { padding:7px 13px; border:1px solid var(--sage); border-radius:8px; background:var(--cream); color:var(--ink); font-family:inherit; font-size:0.9em; cursor:pointer; transition: background .15s, border-color .15s; }
        .btn:hover { background:#fff; border-color:var(--forest); }
        .btn.primary { background:var(--ink); color:#fff; border-color:var(--ink); }
        .btn.primary:hover { background:var(--forest); border-color:var(--forest); }
        .actions { display:flex; flex-wrap:wrap; gap:8px; }
        .swatches { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
        .swatch { width:38px; height:38px; border-radius:9px; border:1px solid var(--line); cursor:pointer; transition: transform .12s; }
        .swatch:hover { transform: scale(1.06); }
        .toggle { display:inline-flex; align-items:center; gap:10px; cursor:pointer; margin-left:14px; }
        .toggle input { width:18px; height:18px; cursor:pointer; }
        .hint { font-size:0.82em; color:var(--slate); margin-top:8px; }
        /* 2D drag-pads for head + eyes */
        .pads-row { display:flex; flex-wrap:wrap; gap:22px; align-items:flex-start; justify-content:center; }
        .pad-block { display:flex; flex-direction:column; align-items:center; gap:8px; }
        .pad-block .lbl { font-size:0.82em; color:var(--slate); font-family:'IBM Plex Mono', monospace; letter-spacing:0.05em; }
        .pad { position:relative; width:188px; height:188px; background:var(--cream); border:2px solid var(--sage); border-radius:16px; touch-action:none; user-select:none; cursor:grab; }
        .pad:active { cursor:grabbing; }
        .pad .knob { position:absolute; width:32px; height:32px; background:var(--forest); border-radius:50%; left:50%; top:50%; transform:translate(-50%,-50%); pointer-events:none; box-shadow:0 2px 8px rgba(26,46,26,0.25); }
        .pad .cx, .pad .cy { position:absolute; background:var(--ink); opacity:0.14; pointer-events:none; }
        .pad .cx { left:0; right:0; top:50%; height:1px; }
        .pad .cy { top:0; bottom:0; left:50%; width:1px; }
        .pad-axes { display:flex; justify-content:space-between; width:188px; font-size:0.72em; color:var(--slate); font-family:'IBM Plex Mono', monospace; }
        /* Custom expression chips */
        .chip-row { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
        .expr-chip { display:inline-flex; align-items:center; gap:6px; padding:6px 10px; background:#eef4ee; border:1px solid var(--sage); border-radius:20px; font-size:0.92em; color:var(--ink); cursor:pointer; }
        .expr-chip:hover { background:#dfecdf; }
        .expr-chip .x { display:inline-block; width:18px; height:18px; line-height:16px; text-align:center; border-radius:50%; background:rgba(0,0,0,0.08); color:var(--ink); font-size:0.82em; }
        .expr-chip .x:hover { background:rgba(0,0,0,0.18); }
        @media (max-width: 560px) {
            .row { grid-template-columns: 90px 1fr 50px; }
            .row button.primary { grid-column: 1 / -1; }
            .pad, .pad-axes { width: 160px; } .pad { height: 160px; }
        }
    </style>
</head>
<body>
<div class="wrap">
    <div class="head">
        <h1>{{ head_robot_name }}'s Head — Tuning</h1>
        <a href="/">← Home</a>
    </div>

    <div class="card">
        <h2>Status</h2>
        <span id="status" class="status off">Checking…</span>
        <button class="btn" id="reconnectBtn" style="margin-left:10px;">Reconnect</button>
        <button class="btn" id="connHeadBtn" style="margin-left:10px; display:none;">Connect head (USB-C)</button>
        <label class="toggle"><input type="checkbox" id="autoToggle"><span>Thoughtful idle movement</span></label>
        <div class="hint">If "Not connected," close the Ohbot desktop app, then click Reconnect (no full restart needed).</div>
        <div id="idleBox" style="margin-top:14px; padding-top:12px; border-top:1px dashed var(--line);">
            <div class="row" style="grid-template-columns: 130px 1fr 56px;"><span class="name">How often</span><input type="range" id="idleFreq" min="0" max="10" step="0.5" value="7"><span class="val" id="vIdleFreq">7</span></div>
            <div class="row" style="grid-template-columns: 130px 1fr 56px;"><span class="name">How big</span><input type="range" id="idleAmp" min="0" max="10" step="0.5" value="5"><span class="val" id="vIdleAmp">5</span></div>
            <div class="hint" style="margin-top:4px;">"How often" sets how frequently a small motion happens (0 quiet → 10 nearly constant). "How big" scales each motion (0 subtle → 10 expressive).</div>
        </div>
    </div>

    <div class="card">
        <h2>Live direction</h2>
        <div class="sub">Drag inside the squares — left pad steers Blue's <b>head</b> (turn + nod), right pad steers his <b>eyes</b> (look + tilt). Tap <b>Snap to neutral</b> to recentre both.</div>
        <div class="pads-row">
            <div class="pad-block">
                <div class="lbl">HEAD</div>
                <div id="padHead" class="pad"><div class="cx"></div><div class="cy"></div><div class="knob"></div></div>
                <div class="pad-axes"><span>← turn →</span><span>↑ nod ↓</span></div>
            </div>
            <div class="pad-block">
                <div class="lbl">EYES</div>
                <div id="padEyes" class="pad"><div class="cx"></div><div class="cy"></div><div class="knob"></div></div>
                <div class="pad-axes"><span>← look →</span><span>↑ tilt ↓</span></div>
            </div>
        </div>
        <div style="margin-top:14px; display:flex; gap:10px; flex-wrap:wrap; justify-content:center;">
            <button class="btn" id="snapNeutralBtn">Snap to neutral</button>
        </div>
    </div>

    <div class="card">
        <h2>Calibration</h2>
        <div class="sub">Drag a slider to move that motor. When it looks right, tap <b>Save as neutral</b> — that becomes the rest position the rest of Blue uses. Saved automatically; survives restarts.</div>
        <div id="motors"></div>
        <div style="margin-top:14px; display:flex; gap:10px; flex-wrap:wrap;">
            <button class="btn" id="parkBtn">Park all at neutral</button>
            <button class="btn" id="restoreBtn">Restore factory defaults</button>
        </div>
    </div>

    <div class="card">
        <h2>Expression &amp; motion</h2>
        <div class="actions" id="actBox"></div>
        <div style="margin-top:12px; padding-top:10px; border-top:1px dashed var(--line);">
            <div class="sub" style="margin-bottom:8px;">Your saved poses. Move {{ head_robot_name }} with the pads or sliders into a pose, then save it.</div>
            <div class="chip-row" id="customExpr"></div>
            <div style="margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;">
                <button class="btn primary" id="savePoseBtn">Save current pose as…</button>
                <button class="btn" id="demoBtn">Run demo (every motion)</button>
            </div>
        </div>
    </div>

    <div class="card">
        <h2>Hands-free sensitivity</h2>
        <div class="sub">How easily the ear button on the chat page wakes {{ head_robot_name }}. <b>Low</b> = strict (fewer false triggers, may miss soft speech). <b>High</b> = sensitive (catches quiet talkers, may trigger on background noise). After changing, reload the chat page for it to take effect.</div>
        <div class="row" style="grid-template-columns: 130px 1fr 56px;">
            <span class="name">Sensitivity</span>
            <input type="range" id="hfSens" min="0" max="10" step="0.5" value="5">
            <span class="val" id="vHfSens">5.0</span>
        </div>
    </div>

    <div class="card">
        <h2>Lip-sync polarity</h2>
        <div class="sub">If when {{ head_robot_name }} talks both lips move in the same direction together, flip one of these. Tap <b>Test lip-sync</b> to watch the mouth open and close for 4 seconds without speaking.</div>
        <div class="row" style="grid-template-columns: 130px 1fr; margin:6px 0 10px;">
            <span class="name">Talking drive</span>
            <select id="lipDrive" style="padding:6px 8px;border-radius:8px;border:1px solid var(--line);background:var(--card,#1b1b1b);color:var(--fg,#eee);font:inherit;">
                <option value="both">Both lips</option>
                <option value="top">Top lip only</option>
                <option value="bottom">Jaw only (bottom lip)</option>
            </select>
        </div>
        <div class="hint">Which lip(s) move while {{ head_robot_name }} talks. The lip you <i>don't</i> pick is <b>powered off</b> so it can't strain. If one lip jams against a stop and won't move without straining, switch to <b>Jaw only</b> — the jaw alone reads clearly as talking, and the stuck lip goes quiet instead of buzzing.</div>
        <label class="toggle"><input type="checkbox" id="invTop"><span>Invert top lip direction</span></label>
        <label class="toggle"><input type="checkbox" id="invBot"><span>Invert bottom lip direction</span></label>
        <div style="margin-top:12px; padding-top:10px; border-top:1px dashed var(--line);">
            <div class="row" style="grid-template-columns: 130px 1fr 56px;"><span class="name">Top lip travel</span><input type="range" id="lipRngTop" min="0.2" max="3" step="0.1" value="1.8"><span class="val" id="vLipRngTop">1.8</span></div>
            <div class="row" style="grid-template-columns: 130px 1fr 56px;"><span class="name">Jaw travel</span><input type="range" id="lipRngBot" min="0.2" max="4" step="0.1" value="3.0"><span class="val" id="vLipRngBot">3.0</span></div>
            <div class="hint">How far each lip swings from its neutral while talking. <b>If a lip reaches a mechanical stop and sticks mid-speech, turn its travel down</b> until it never gets there; turn up for a more expressive mouth. Press Test lip-sync after each change.</div>
            <div class="row" style="grid-template-columns: 130px 1fr 56px; margin-top:8px;"><span class="name">Lip speed</span><input type="range" id="lipSpeed" min="1" max="10" step="0.5" value="10"><span class="val" id="vLipSpeed">10</span></div>
            <div class="hint">How fast the lips move while talking (10 = snappiest). Turn it down if a lip servo can't keep up with a fast flap; turn it up for crisper speech.</div>
        </div>
        <div style="margin-top:12px; display:flex; gap:10px; flex-wrap:wrap;">
            <button class="btn primary" id="testLipBtn">Test lip-sync (4 sec)</button>
            <button class="btn" id="sweepLipBtn">Full-range lip sweep (~8 sec)</button>
            <button class="btn" id="relaxLipBtn">Relax lip servos</button>
        </div>
        <div class="hint">The talking flap only moves each lip a small way from its saved neutral — if a lip's neutral sits where the mechanism is jammed against a stop, talking looks frozen. The sweep drives the <b>top lip</b> slowly through its usable range, then the <b>bottom lip</b>. Watch where each lip really moves, then set that lip's neutral (Calibration sliders above) inside the moving zone. A lip that stays still for the whole sweep has a loose servo arm or linkage. <b>Note:</b> sliders reach positions the mouth physically can't — the top lip rests on a centre stop near mid-range and can't go below it unless the jaw is wide open, so dragging it low with the mouth closed just stalls the motor and "sticks" until you drag back past the stop.</div>
        <div class="hint"><b>Relax lip servos</b> powers off just the two lip motors so a jammed mouth can be moved by hand without the motors fighting back (a stalled servo strains, buzzes and overheats). They wake again on the next lip command — talking, a lip slider, the test or sweep buttons — or a reset.</div>
    </div>

    <div class="card">
        <h2>Eye colour</h2>
        <div class="row" style="grid-template-columns: 110px 1fr 56px;"><span class="name">Red</span><input type="range" id="cR" min="0" max="10" step="1" value="0"><span class="val" id="vR">0</span></div>
        <div class="row" style="grid-template-columns: 110px 1fr 56px;"><span class="name">Green</span><input type="range" id="cG" min="0" max="10" step="1" value="0"><span class="val" id="vG">0</span></div>
        <div class="row" style="grid-template-columns: 110px 1fr 56px;"><span class="name">Blue</span><input type="range" id="cB" min="0" max="10" step="1" value="0"><span class="val" id="vB">0</span></div>
        <div class="swatches" id="swatches"></div>
    </div>
</div>

<script src="/js/ohbot-heads.js"></script>
<script>
const MOTORS = [[0,'HeadNod'],[1,'HeadTurn'],[7,'HeadRoll'],[2,'EyeTurn'],[6,'EyeTilt'],[3,'LidBlink'],[4,'TopLip'],[5,'BottomLip']];
const ACTIONS = ['nod_yes','shake_no','blink','wink','look_left','look_right','look_up','look_down','look_center','happy','sad','surprised','curious','neutral'];
const COLOURS = [
  ['Off',0,0,0,'#222'], ['Blue',0,2,10,'#3b82f6'], ['Pink',10,2,7,'#ff7eb3'],
  ['Yellow',10,7,0,'#f0c419'], ['Green',2,10,3,'#4ade80'], ['Purple',7,3,10,'#a78bfa'],
  ['Orange',10,5,0,'#fb923c'], ['Warm white',10,8,6,'#f9e3c2']
];

// Which head this page tunes — "blue" (/head) or "hexia" (/head/hexia). Every
// /head/* control is rewritten to that head's robot-scoped route.
const HEAD_ROBOT = "{{ head_robot }}";
function _hurl(url) {
    return (typeof url === 'string' && url.indexOf('/head/') === 0)
        ? ('/head/' + HEAD_ROBOT + url.slice(5)) : url;
}
async function _serverPOST(url, body) {
    try {
        const r = await fetch(_hurl(url), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{})});
        return await r.json().catch(() => null);
    } catch (e) { return null; }
}
async function postJSON(url, body) {
    body = body || {};
    // A head plugged into THIS device (Web Serial) takes over from the server:
    // movement/test verbs run on it directly; persistence verbs still POST to the
    // server (saving into the shared calibration), then we refresh the local
    // head's copy so the change takes effect. Reads (getJSON) still hit the server.
    if (LOCAL_DRIVERS[HEAD_ROBOT]) {
        if (localHeadControl(HEAD_ROBOT, url, body)) return { ok: true, local: true };
        const res = await _serverPOST(url, body);
        if (url !== '/head/reconnect') { try { LOCAL_DRIVERS[HEAD_ROBOT].calib = await _fetchCalib(HEAD_ROBOT); } catch (e) {} }
        return res;
    }
    return await _serverPOST(url, body);
}
async function getJSON(url) {
    try { const r = await fetch(_hurl(url)); return await r.json(); } catch (e) { return null; }
}

function buildMotors(centers) {
    const cont = document.getElementById('motors'); cont.innerHTML = '';
    for (const [m, name] of MOTORS) {
        const c = (centers && centers[m] != null) ? centers[m] : 5;
        const row = document.createElement('div'); row.className = 'row';
        row.innerHTML = '<span class="name">' + name + '</span>'
          + '<input type="range" min="0" max="10" step="0.1" value="' + c + '">'
          + '<span class="val">' + Number(c).toFixed(1) + '</span>'
          + '<button class="btn primary">Save as neutral</button>';
        const slider = row.querySelector('input');
        const valEl  = row.querySelector('.val');
        const saveBt = row.querySelector('button');
        let pending = null;
        slider.addEventListener('input', () => {
            const pos = parseFloat(slider.value);
            valEl.textContent = pos.toFixed(1);
            // Throttle: at most one request in flight per motor.
            if (pending) { pending.next = pos; return; }
            pending = {pos: pos, next: null};
            (async function drain(){
                while (pending) {
                    const p = pending.pos;
                    await postJSON('/head/move', {motor: m, pos: p});
                    if (pending.next != null) { pending.pos = pending.next; pending.next = null; }
                    else { pending = null; }
                }
            })();
        });
        saveBt.addEventListener('click', async () => {
            await postJSON('/head/calibrate', {motor: m, pos: parseFloat(slider.value)});
            saveBt.textContent = 'Saved ✓';
            setTimeout(() => { saveBt.textContent = 'Save as neutral'; }, 1100);
        });
        cont.appendChild(row);
    }
}

function buildActions() {
    const box = document.getElementById('actBox');
    for (const a of ACTIONS) {
        const b = document.createElement('button'); b.className = 'btn';
        b.textContent = a.replace(/_/g, ' ').replace(/\\b\\w/g, c => c.toUpperCase());
        b.addEventListener('click', () => postJSON('/head/action', {action: a}));
        box.appendChild(b);
    }
}

function buildSwatches() {
    const box = document.getElementById('swatches');
    for (const [name, r, g, b, css] of COLOURS) {
        const s = document.createElement('div'); s.className = 'swatch'; s.title = name; s.style.background = css;
        s.addEventListener('click', () => setColour(r, g, b));
        box.appendChild(s);
    }
}

function wireColour(id) {
    const s = document.getElementById('c'+id), v = document.getElementById('v'+id);
    s.addEventListener('input', () => {
        v.textContent = s.value;
        const r = +document.getElementById('cR').value, g = +document.getElementById('cG').value, b = +document.getElementById('cB').value;
        postJSON('/head/eye-color', {r, g, b});
    });
}
function setColour(r, g, b) {
    document.getElementById('cR').value = r; document.getElementById('vR').textContent = r;
    document.getElementById('cG').value = g; document.getElementById('vG').textContent = g;
    document.getElementById('cB').value = b; document.getElementById('vB').textContent = b;
    postJSON('/head/eye-color', {r, g, b});
}

let CURRENT_STATE = null;

async function loadState() {
    const s = await getJSON('/head/state');
    CURRENT_STATE = s;
    const status = document.getElementById('status');
    if (LOCAL_DRIVERS[HEAD_ROBOT]) { status.className = 'status on'; status.textContent = 'Connected (this device, USB-C)'; }
    else if (s && s.available) { status.className = 'status on'; status.textContent = 'Connected'; }
    else { status.className = 'status off'; status.textContent = 'Not connected'; }
    buildMotors(s && s.centers);
    buildCustomExpressions(s && s.custom_expressions);
    centerPads(s && s.centers);
    document.getElementById('autoToggle').checked = !!(s && s.auto_movement);
    document.getElementById('invTop').checked = !!(s && s.lip_invert_top);
    document.getElementById('invBot').checked = !!(s && s.lip_invert_bottom);
    if (s && s.lip_drive) document.getElementById('lipDrive').value = s.lip_drive;
    if (s && s.lip_top_range != null) {
        document.getElementById('lipRngTop').value = s.lip_top_range;
        document.getElementById('vLipRngTop').textContent = Number(s.lip_top_range).toFixed(1);
    }
    if (s && s.lip_bottom_range != null) {
        document.getElementById('lipRngBot').value = s.lip_bottom_range;
        document.getElementById('vLipRngBot').textContent = Number(s.lip_bottom_range).toFixed(1);
    }
    if (s && s.lip_speed != null) {
        document.getElementById('lipSpeed').value = s.lip_speed;
        document.getElementById('vLipSpeed').textContent = Number(s.lip_speed).toFixed(1);
    }
    if (s && s.idle_frequency != null) {
        document.getElementById('idleFreq').value = s.idle_frequency;
        document.getElementById('vIdleFreq').textContent = Number(s.idle_frequency).toFixed(1);
    }
    if (s && s.idle_amplitude != null) {
        document.getElementById('idleAmp').value = s.idle_amplitude;
        document.getElementById('vIdleAmp').textContent = Number(s.idle_amplitude).toFixed(1);
    }
    if (s && s.hf_sensitivity != null) {
        document.getElementById('hfSens').value = s.hf_sensitivity;
        document.getElementById('vHfSens').textContent = Number(s.hf_sensitivity).toFixed(1);
    }
}

function wireIdle(id, key) {
    const s = document.getElementById('idle' + id), v = document.getElementById('vIdle' + id);
    let pending = null;
    s.addEventListener('input', () => {
        v.textContent = Number(s.value).toFixed(1);
        if (pending) { pending.next = s.value; return; }
        pending = {val: s.value, next: null};
        (async function drain(){
            while (pending) {
                const body = {}; body[key] = parseFloat(pending.val);
                await postJSON('/head/idle-config', body);
                if (pending.next != null) { pending.val = pending.next; pending.next = null; }
                else { pending = null; }
            }
        })();
    });
}
wireIdle('Freq', 'frequency');
wireIdle('Amp', 'amplitude');

// Hands-free sensitivity slider (chat pages read this at next load).
(function () {
    const s = document.getElementById('hfSens'), v = document.getElementById('vHfSens');
    if (!s) return;
    let pending = null;
    s.addEventListener('input', () => {
        v.textContent = Number(s.value).toFixed(1);
        if (pending) { pending.next = s.value; return; }
        pending = {val: s.value, next: null};
        (async function drain(){
            while (pending) {
                await postJSON('/head/hf-config', {sensitivity: parseFloat(pending.val)});
                if (pending.next != null) { pending.val = pending.next; pending.next = null; }
                else { pending = null; }
            }
        })();
    });
})();

document.getElementById('autoToggle').addEventListener('change', e => postJSON('/head/auto', {enabled: e.target.checked}));
document.getElementById('invTop').addEventListener('change', e => postJSON('/head/lip-config', {invert_top: e.target.checked}));
document.getElementById('invBot').addEventListener('change', e => postJSON('/head/lip-config', {invert_bottom: e.target.checked}));
document.getElementById('lipRngTop').addEventListener('input', e => { document.getElementById('vLipRngTop').textContent = Number(e.target.value).toFixed(1); });
document.getElementById('lipRngTop').addEventListener('change', e => postJSON('/head/lip-config', {top_range: parseFloat(e.target.value)}));
document.getElementById('lipRngBot').addEventListener('input', e => { document.getElementById('vLipRngBot').textContent = Number(e.target.value).toFixed(1); });
document.getElementById('lipRngBot').addEventListener('change', e => postJSON('/head/lip-config', {bottom_range: parseFloat(e.target.value)}));
document.getElementById('lipSpeed').addEventListener('input', e => { document.getElementById('vLipSpeed').textContent = Number(e.target.value).toFixed(1); });
document.getElementById('lipSpeed').addEventListener('change', e => postJSON('/head/lip-config', {flap_speed: parseFloat(e.target.value)}));
document.getElementById('lipDrive').addEventListener('change', e => postJSON('/head/lip-config', {drive: e.target.value}));
document.getElementById('testLipBtn').addEventListener('click', async () => {
    const btn = document.getElementById('testLipBtn');
    btn.disabled = true; const orig = btn.textContent; btn.textContent = 'Testing…';
    try { await postJSON('/head/lip-test', {}); } finally { btn.disabled = false; btn.textContent = orig; }
});
document.getElementById('sweepLipBtn').addEventListener('click', async () => {
    const btn = document.getElementById('sweepLipBtn');
    btn.disabled = true; const orig = btn.textContent; btn.textContent = 'Sweeping — watch the mouth…';
    // The route returns immediately (the sweep runs on the robot in the
    // background); keep the button down for its duration so taps don't overlap.
    try { await postJSON('/head/lip-sweep', {}); await new Promise(r => setTimeout(r, 8500)); }
    finally { btn.disabled = false; btn.textContent = orig; }
});
document.getElementById('relaxLipBtn').addEventListener('click', async () => {
    const btn = document.getElementById('relaxLipBtn');
    btn.disabled = true; const orig = btn.textContent;
    const d = await postJSON('/head/lip-relax', {});
    btn.textContent = (d && d.ok) ? 'Lips relaxed — move them by hand' : 'Relax failed — connected?';
    setTimeout(() => { btn.disabled = false; btn.textContent = orig; }, 2500);
});
document.getElementById('parkBtn').addEventListener('click', async () => { await postJSON('/head/reset', {}); });
document.getElementById('restoreBtn').addEventListener('click', async () => {
    if (!confirm('Reset all neutral positions to factory defaults?')) return;
    await postJSON('/head/restore-defaults', {});
    loadState();
});

buildActions(); buildSwatches();
wireColour('R'); wireColour('G'); wireColour('B');

// ---- 2D drag-pads for head + eyes ----
const PAD_RANGE = 2.5;  // motor units of swing from centre in each direction
function makePad(opts) {
    const pad = document.getElementById(opts.padId);
    const knob = pad.querySelector('.knob');
    let dragging = false, pending = null;
    function center() {
        const c = (CURRENT_STATE && CURRENT_STATE.centers) || {};
        return { xc: (c[opts.xMotor] != null ? c[opts.xMotor] : 5),
                 yc: (c[opts.yMotor] != null ? c[opts.yMotor] : 5) };
    }
    function applyAt(clientX, clientY) {
        const r = pad.getBoundingClientRect();
        let nx = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
        let ny = Math.max(0, Math.min(1, (clientY - r.top) / r.height));
        knob.style.left = (nx * 100) + '%';
        knob.style.top = (ny * 100) + '%';
        const c = center();
        const sx = opts.xInvert ? -1 : 1, sy = opts.yInvert ? -1 : 1;
        const xPos = Math.max(0, Math.min(10, c.xc + sx * (nx - 0.5) * 2 * PAD_RANGE));
        const yPos = Math.max(0, Math.min(10, c.yc + sy * (ny - 0.5) * 2 * PAD_RANGE));
        if (pending) { pending.x = xPos; pending.y = yPos; return; }
        pending = { x: xPos, y: yPos };
        (async function drain() {
            while (pending) {
                const xp = pending.x, yp = pending.y;
                await postJSON('/head/move', {motor: opts.xMotor, pos: xp});
                await postJSON('/head/move', {motor: opts.yMotor, pos: yp});
                pending = null;
            }
        })();
    }
    pad.addEventListener('pointerdown', e => { dragging = true; pad.setPointerCapture(e.pointerId); applyAt(e.clientX, e.clientY); });
    pad.addEventListener('pointermove', e => { if (dragging) applyAt(e.clientX, e.clientY); });
    const up = () => { dragging = false; };
    pad.addEventListener('pointerup', up); pad.addEventListener('pointercancel', up); pad.addEventListener('pointerleave', up);
}

function centerPads() {
    document.querySelectorAll('.pad .knob').forEach(k => { k.style.left = '50%'; k.style.top = '50%'; });
}

// Head pad: x = HeadTurn (right on pad → physically right → lower HEADTURN value, so xInvert=true),
//           y = HeadNod (up on pad → head up → higher HEADNOD, so yInvert=true).
makePad({ padId: 'padHead', xMotor: 1, yMotor: 0, xInvert: true, yInvert: true });
// Eye pad: x = EyeTurn (same convention as HeadTurn), y = EyeTilt (higher = up).
makePad({ padId: 'padEyes', xMotor: 2, yMotor: 6, xInvert: true, yInvert: true });

document.getElementById('snapNeutralBtn').addEventListener('click', async () => {
    await postJSON('/head/reset', {});
    centerPads();
});

// ---- Custom expressions ----
function buildCustomExpressions(map) {
    const cont = document.getElementById('customExpr'); cont.innerHTML = '';
    const names = Object.keys(map || {}).sort();
    if (!names.length) {
        cont.innerHTML = '<span class="hint">No saved poses yet — move Blue, then click "Save current pose as…".</span>';
        return;
    }
    for (const name of names) {
        const chip = document.createElement('span'); chip.className = 'expr-chip';
        const lbl = document.createElement('span'); lbl.className = 'lbl'; lbl.textContent = name;
        const x = document.createElement('span'); x.className = 'x'; x.title = 'Delete'; x.textContent = '×';
        chip.appendChild(lbl); chip.appendChild(x);
        lbl.addEventListener('click', () => postJSON('/head/expression', {name}));
        x.addEventListener('click', async (e) => {
            e.stopPropagation();
            if (!confirm('Delete the pose "' + name + '"?')) return;
            await postJSON('/head/expression-delete', {name});
            loadState();
        });
        cont.appendChild(chip);
    }
}

document.getElementById('savePoseBtn').addEventListener('click', async () => {
    const name = (prompt('Name this pose:') || '').trim();
    if (!name) return;
    const r = await postJSON('/head/expression-save', {name});
    if (r && r.ok === false) {
        alert('Could not save: ' + (r.error || 'unknown'));
        return;
    }
    loadState();
});

// ---- Demo + reconnect ----
document.getElementById('demoBtn').addEventListener('click', async () => {
    const btn = document.getElementById('demoBtn');
    btn.disabled = true; const orig = btn.textContent; btn.textContent = 'Running demo…';
    try { await postJSON('/head/demo', {}); } finally {
        setTimeout(() => { btn.disabled = false; btn.textContent = orig; }, 22000);
    }
});

document.getElementById('reconnectBtn').addEventListener('click', async () => {
    const btn = document.getElementById('reconnectBtn');
    btn.disabled = true; const orig = btn.textContent; btn.textContent = 'Reconnecting…';
    try { await postJSON('/head/reconnect', {}); }
    finally { btn.disabled = false; btn.textContent = orig; loadState(); }
});

loadState();

// Local USB-C head (Web Serial): tune a head plugged into THIS device. The
// movement controls drive it directly (see postJSON above); the save/config
// controls still persist to the shared calibration on the server, then refresh
// the local head's copy. Shown only on a capable non-PC device (Chrome + https);
// the PC keeps tuning the server-driven board as before.
(function () {
    const btn = document.getElementById('connHeadBtn');
    if (!btn || !(WEBSERIAL_OK && !DRIVES_HEADS)) return;
    btn.style.display = '';
    function paint() {
        const on = !!LOCAL_DRIVERS[HEAD_ROBOT];
        btn.classList.toggle('active', on);
        btn.textContent = on ? 'Release head' : 'Connect head (USB-C)';
        const st = document.getElementById('status');
        if (st) {
            if (on) { st.className = 'status on'; st.textContent = 'Connected (this device, USB-C)'; }
            else { st.className = 'status off'; st.textContent = 'Not connected'; }
        }
    }
    window.onLocalHeadsChanged = paint;
    btn.addEventListener('click', function () {
        if (LOCAL_DRIVERS[HEAD_ROBOT]) disconnectHead(HEAD_ROBOT); else connectHead(HEAD_ROBOT);
    });
    paint();
})();
</script>
</body>
</html>"""

OHBOT_HEADS_JS = """
/* Web Serial Ohbot driver shared across the duet, chat and calibration pages.
   A faithful JS port of the ohbot wire protocol + blue/head.py behaviour, so a
   head plugged into THIS device's USB-C port lip-syncs, idles, emotes and
   calibrates exactly like it does on the PC. Calibration per head is pulled from
   /head/<head>/state. Needs Chrome/Edge on a secure (https) origin. */
var _ENC = new TextEncoder();
function _clip(v,lo,hi){ v=Number(v); if(isNaN(v)) v=lo; return v<lo?lo:(v>hi?hi:v); }
function _rand(a,b){ return a + Math.random()*(b-a); }
function _sleepS(s){ return new Promise(function(res){ setTimeout(res, Math.max(0, s*1000)); }); }

// Motor channels + per-motor scaling from ohbotData/MotorDefinitionsv21.omd
// (min/max as the library derives them: int(raw/1000*180)). Every Ohbot motor
// takes the plain servo path.
var HEADNOD=0, HEADTURN=1, EYETURN=2, LIDBLINK=3, TOPLIP=4, BOTTOMLIP=5, EYETILT=6, HEADROLL=7;
var _MOTOR_MIN = {0:25,1:0,2:68,3:6,4:0,5:0,6:93,7:72};
var _MOTOR_MAX = {0:126,1:180,2:140,3:54,4:99,5:99,6:165,7:108};
var _MOTOR_REV = {0:true,1:false,2:false,3:false,4:true,5:true,6:false,7:true};
var _IDLE_RECIPES = [
  ['blink',null],['blink',null],
  ['nudge',[HEADNOD,[-0.8,-0.5,0.5,0.8],3,0.6,1.1]],
  ['nudge',[HEADTURN,[-1.0,-0.6,0.6,1.0],3,0.8,1.4]],
  ['nudge',[HEADROLL,[-0.6,-0.4,0.4,0.6],3,0.8,1.4]],
  ['nudge',[EYETURN,[1.5,-1.5],6,0.4,0.8]],
  ['nudge',[EYETILT,[1.2,-1.2],5,0.4,0.9]]
];
// Built-in expression poses (offsets from calibrated centres) — mirror head.py.
var _EXPRESSIONS = {
  neutral:{1:0,0:0,4:0,5:0,3:0,2:0,6:0},
  happy:{0:1.0,4:3.0,5:-3.0,3:0},
  sad:{0:-2.0,4:-3.0,5:3.0,3:-4.0},
  surprised:{0:2.0,4:0,5:4.0,3:2.0},
  curious:{1:1.5,0:1.0,7:1.0,2:1.0,3:0},
  wink:{3:-8.0}
};
var _LOOK_OFFSETS = { left:[HEADTURN,3.0], right:[HEADTURN,-3.0], up:[HEADNOD,3.0], down:[HEADNOD,-2.5] };

class OhbotSerialDriver {
  constructor(port, calib){
    this.port=port; this.calib=calib||{};
    this.writer=port.writable.getWriter();
    this._chain=Promise.resolve();
    this.lipToken=0; this.lipActive=false; this.busyUntil=0; this.closed=false;
  }
  // Serialize writes through a promise chain (mirrors the library's `writing`
  // flag) so commands never interleave on the wire.
  _write(s){
    var self=this;
    this._chain=this._chain.then(function(){
      if(self.closed || !self.writer) return;
      return self.writer.write(_ENC.encode(s)).catch(function(){});
    });
    return this._chain;
  }
  center(m){
    var c=(this.calib&&this.calib.centers)?this.calib.centers[m]:undefined;
    if(c===undefined||c===null||isNaN(Number(c))) return (m===LIDBLINK?8:5);
    return Number(c);
  }
  _cal(k,dflt){ var v=this.calib?this.calib[k]:undefined; return (v===undefined||v===null)?dflt:v; }
  // Exact reproduction of ohbot.move() for the servo path.
  move(m,pos,spd){
    m=Number(m); pos=_clip(pos,0,10); spd=_clip(spd,0,10);
    if(m===BOTTOMLIP && pos<5) pos = 5 - (5-pos)/2;
    if(_MOTOR_REV[m]) pos = 10 - pos;
    // Always (re)attach before moving: a board reset detaches every servo and we
    // can't see that over Web Serial, so a cached "attached" would make later
    // moves no-ops (this is what broke Hexia). Attach is idempotent.
    this._write('a0'+m+'\\n');
    var absPos=Math.trunc((_MOTOR_MAX[m]-_MOTOR_MIN[m])/10*pos + _MOTOR_MIN[m]);
    var s=25*spd; var sstr=(s===Math.trunc(s))?(s+'.0'):String(s);
    this._write('m0'+m+','+absPos+','+sstr+'\\n');
  }
  eyeColour(r,g,b){
    // The eye LEDs read channels in G,R,B order (red requests lit the eyes
    // green and vice versa) — swap on the way out, mirroring blue/head.py.
    if(this._cal('eye_swap_rg',true)){ var _t=r; r=g; g=_t; }
    r=Math.trunc(255/10*_clip(r,0,10)); g=Math.trunc(255/10*_clip(g,0,10)); b=Math.trunc(255/10*_clip(b,0,10));
    this._write('l00,'+r+','+g+','+b+'\\n'); this._write('l01,'+r+','+g+','+b+'\\n');
  }
  // ---- mouth + lip sequence (mirror blue/head.py _set_mouth / _lip_seq_loop) ----
  _excludedLips(){ var d=String(this._cal('lip_drive','both')).toLowerCase(); if(d==='top') return [BOTTOMLIP]; if(d==='bottom'||d==='jaw') return [TOPLIP]; return []; }
  _detachExcluded(){ var e=this._excludedLips(); for(var i=0;i<e.length;i++){ try{ this._write('d0'+e[i]+'\\n'); }catch(_e){} } }
  _setMouth(openness){
    openness=_clip(openness,0,1);
    var topSign=this._cal('lip_invert_top',false)?-1:1;
    var botSign=this._cal('lip_invert_bottom',false)?-1:1;
    var topRng=Number(this._cal('lip_top_range',1.8));
    var botRng=Number(this._cal('lip_bottom_range',3.0));
    var flapSpd=_clip(Number(this._cal('lip_speed',10)),1,10);
    var excl=this._excludedLips();
    if(excl.indexOf(TOPLIP)<0) this.move(TOPLIP, _clip(this.center(TOPLIP)+topSign*topRng*openness, 0.25, 9.75), flapSpd);
    if(excl.indexOf(BOTTOMLIP)<0) this.move(BOTTOMLIP, _clip(this.center(BOTTOMLIP)+botSign*botRng*openness, 0.25, 9.75), flapSpd);
  }
  playLipSequence(frames){
    if(!frames||!frames.length) return;
    this.lipToken++; var my=this.lipToken; this.lipActive=true; this._detachExcluded(); var self=this;
    (async function(){
      for(var i=0;i<frames.length;i++){
        if(self.closed || self.lipToken!==my || !self.lipActive) break;
        var op=_clip(frames[i][0],0,1), hold=_clip(frames[i][1],0.01,1.5);
        self._setMouth(op); await _sleepS(hold);
      }
      // Frame durations only ESTIMATE the TTS length; if the voice runs longer,
      // keep flapping until lipStop (onend) so the mouth doesn't freeze mid-sentence.
      var deadline=Date.now()+90000;
      while(self.lipActive && self.lipToken===my && !self.closed && Date.now()<deadline){
        self._setMouth(0.6+Math.random()*0.4); await _sleepS(0.09+Math.random()*0.05);
        if(!self.lipActive || self.lipToken!==my) break;
        self._setMouth(0); await _sleepS(0.07+Math.random()*0.05);
      }
      if(self.lipToken===my){ self._setMouth(0); self.lipActive=false; }
    })();
  }
  lipStop(){ this.lipToken++; this.lipActive=false; this._setMouth(0); }
  // ---- named actions (mirror blue/head.py) ----
  look(d, speed){
    d=(d||'').toLowerCase().trim(); speed=speed||4; this.busyUntil=Date.now()+1000;
    if(['center','centre','forward','front','straight','ahead'].indexOf(d)>=0){
      this.move(HEADTURN,this.center(HEADTURN),speed); this.move(HEADNOD,this.center(HEADNOD),speed); return true;
    }
    var spec=_LOOK_OFFSETS[d]; if(!spec) return false;
    this.move(spec[0], this.center(spec[0])+spec[1], speed); return true;
  }
  nodYes(times){
    times=Math.max(1,Math.min(5,times||2)); var c=this.center(HEADNOD); this.busyUntil=Date.now()+(times*750+500); var self=this;
    (async function(){ for(var i=0;i<times;i++){ self.move(HEADNOD,c-2,7); await _sleepS(0.35); self.move(HEADNOD,c+2,7); await _sleepS(0.35); } self.move(HEADNOD,c,6); })();
    return true;
  }
  nod(){ return this.nodYes(2); }
  shakeNo(times){
    times=Math.max(1,Math.min(5,times||2)); var c=this.center(HEADTURN); this.busyUntil=Date.now()+(times*750+500); var self=this;
    (async function(){ for(var i=0;i<times;i++){ self.move(HEADTURN,c-2,7); await _sleepS(0.35); self.move(HEADTURN,c+2,7); await _sleepS(0.35); } self.move(HEADTURN,c,6); })();
    return true;
  }
  blink(times){
    times=Math.max(1,Math.min(5,times||1)); var c=this.center(LIDBLINK); this.busyUntil=Date.now()+(times*400+200); var self=this;
    (async function(){ for(var i=0;i<times;i++){ self.move(LIDBLINK,0,10); await _sleepS(0.10); self.move(LIDBLINK,c,10); await _sleepS(0.18); } })();
    return true;
  }
  expression(name, speed){
    name=(name||'').toLowerCase().trim(); var pose=_EXPRESSIONS[name]; if(!pose) return false;
    speed=speed||5; this.busyUntil=Date.now()+800; var self=this;
    for(var k in pose){ var m=Number(k); this.move(m, this.center(m)+pose[k], speed); }
    if(name==='wink'){ (async function(){ await _sleepS(0.25); self.move(LIDBLINK,self.center(LIDBLINK),10); })(); }
    return true;
  }
  applyExpression(name, speed){
    var nm=(name||'').trim();
    if(_EXPRESSIONS[nm.toLowerCase()]) return this.expression(nm, speed);
    var cust=(this.calib.custom_expressions||{})[nm]; if(!cust) return false;
    speed=speed||5; this.busyUntil=Date.now()+800;
    for(var k in cust){ this.move(Number(k), Number(cust[k]), speed); }
    return true;
  }
  action(name, times){
    name=(name||'').toLowerCase().trim(); times=times||2;
    if(name.indexOf('look_')===0) return this.look(name.slice(5));
    if(name==='nod_yes') return this.nodYes(times);
    if(name==='shake_no') return this.shakeNo(times);
    if(name==='blink') return this.blink(times);
    if(['happy','sad','surprised','curious','neutral','wink'].indexOf(name)>=0) return this.expression(name);
    return false;
  }
  lipRelax(){ this.lipToken++; this.lipActive=false; this._write('d0'+TOPLIP+'\\n'); this._write('d0'+BOTTOMLIP+'\\n'); return true; }
  lipTest(){
    this.lipToken++; var my=this.lipToken; this.lipActive=true; this._detachExcluded(); this.busyUntil=Date.now()+3000; var self=this;
    (async function(){
      var t0=Date.now();
      while(self.lipActive && self.lipToken===my && !self.closed && Date.now()-t0<2500){
        self._setMouth(0.85+Math.random()*0.15); await _sleepS(0.08+Math.random()*0.05);
        if(self.lipToken!==my) break;
        self._setMouth(0.0); await _sleepS(0.07+Math.random()*0.05);
      }
      if(self.lipToken===my){ self._setMouth(0); self.lipActive=false; }
    })();
    return true;
  }
  lipSweep(){
    this.lipToken++; var my=this.lipToken; this.lipActive=false; this.busyUntil=Date.now()+16000; var self=this;
    var wp={4:[4,6,8,10,5],5:[2,5,7.5,10,5]};
    (async function(){
      var motors=[TOPLIP,BOTTOMLIP];
      for(var mi=0;mi<motors.length;mi++){ var motor=motors[mi];
        for(var pi=0;pi<wp[motor].length;pi++){ if(self.lipToken!==my||self.closed) return; self.move(motor,wp[motor][pi],3); await _sleepS(0.55); }
        self.move(motor,self.center(motor),4); await _sleepS(0.4);
      }
      if(self.lipToken===my) self._setMouth(0);
    })();
    return true;
  }
  reset(){ this.lipToken++; this.lipActive=false; this.busyUntil=Date.now()+800; this.eyeColour(0,0,0); for(var m=0;m<8;m++) this.move(m,this.center(m),4); return true; }
  // ---- idle motion (mirror blue/head.py _auto_loop) ----
  _intervalRange(){
    var f=_clip(this._cal('idle_frequency',7),0,10)/10;
    var lo=0.8+(1-f)*5.2, hi=2.5+(1-f)*9.5;
    if(this.lipActive){ lo=Math.max(0.35,lo*0.45); hi=Math.max(1.2,hi*0.45); }
    return [lo,hi];
  }
  _ampMult(){
    var a=_clip(this._cal('idle_amplitude',5),0,10);
    var base=(a<=5)?(0.3+(a/5)*0.7):(1.0+((a-5)/5)*1.0);
    return this.lipActive?base*0.7:base;
  }
  _autoEnabled(){ return this._cal('auto_movement',true)!==false; }
  async _doIdleMotion(){
    var r=_IDLE_RECIPES[Math.floor(Math.random()*_IDLE_RECIPES.length)];
    if(r[0]==='blink'){
      var c=this.center(LIDBLINK); this.move(LIDBLINK,0,10); await _sleepS(0.10); this.move(LIDBLINK,c,10);
    } else {
      var sp=r[1], motor=sp[0], choices=sp[1], speed=sp[2], hmin=sp[3], hmax=sp[4];
      var cc=this.center(motor), off=choices[Math.floor(Math.random()*choices.length)];
      this.move(motor, cc+off*this._ampMult(), speed); await _sleepS(_rand(hmin,hmax)); this.move(motor, cc, speed);
    }
  }
  async _autoLoop(){
    await _sleepS(_rand(3,6));   // don't fire the instant we connect
    while(!this.closed){
      var rg=this._intervalRange(); await _sleepS(_rand(rg[0],rg[1]));
      if(this.closed) break;
      try{
        if(this.lipActive){ await this._doIdleMotion(); }
        else if(this._autoEnabled() && Date.now()>=this.busyUntil){ await this._doIdleMotion(); }
      }catch(e){}
    }
  }
  async start(){
    this.closed=false;
    await _sleepS(1.2);   // let the board finish booting if opening reset it
    this.eyeColour(0,0,0);
    for(var m=0;m<8;m++) this.move(m, this.center(m), 4);   // park at calibrated centres
    this._autoLoop();
  }
  async close(){
    this.lipToken++; this.lipActive=false;
    try{ this._setMouth(0); }catch(e){}
    this.closed=true;
    try{ await this._chain; }catch(e){}
    try{ if(this.writer) this.writer.releaseLock(); }catch(e){}
    try{ await this.port.close(); }catch(e){}
    this.writer=null;
  }
}

// Device + capability gates (shared by every page that can drive heads).
function blueDeviceTag(){
  var ua=navigator.userAgent||''; var touch=(navigator.maxTouchPoints||0)>1;
  if(/iPad/.test(ua)||(/Macintosh/.test(ua)&&touch)) return 'ipad';
  if(/iPhone|iPod/.test(ua)) return 'iphone';
  if(/Android/.test(ua)) return 'android';
  if(/Macintosh|Mac OS X/.test(ua)) return 'mac';
  if(/Windows/.test(ua)) return 'windows';
  return 'other';
}
var DRIVES_HEADS = (blueDeviceTag()==='windows');
var WEBSERIAL_OK = ('serial' in navigator) && !!window.isSecureContext;
var LOCAL_DRIVERS = {blue:null, hexia:null};

function _localHeadsNote(msg){ if(window.onLocalHeadsNote){ try{ window.onLocalHeadsNote(msg); return; }catch(e){} } try{ console.warn('[heads] '+msg); }catch(e){} }
function _defaultCalib(){ return {centers:{}, lip_invert_top:false, lip_invert_bottom:false, lip_top_range:1.8, lip_bottom_range:3.0, lip_speed:10, lip_drive:'both', idle_frequency:7, idle_amplitude:5, auto_movement:true}; }
async function _fetchCalib(headName){
  try{ var r=await fetch('/head/'+headName+'/state'); if(r.ok){ var j=await r.json(); if(j&&typeof j==='object') return j; } }catch(e){}
  return _defaultCalib();
}
async function _reparkFor(headName){
  var drv=LOCAL_DRIVERS[headName]; if(!drv) return;
  drv.calib=await _fetchCalib(headName);
  for(var m=0;m<8;m++) drv.move(m, drv.center(m), 4);
}
async function connectHead(headName){
  if(!WEBSERIAL_OK) return;
  var port;
  try{ port=await navigator.serial.requestPort(); }catch(e){ return; }   // user dismissed the picker
  try{ await port.open({baudRate:19200}); }
  catch(e){ _localHeadsNote("couldn't open that USB port for "+headName+": "+(e&&e.message?e.message:e)); return; }
  var calib=await _fetchCalib(headName);
  var drv;
  try{ drv=new OhbotSerialDriver(port, calib); await drv.start(); }
  catch(e){ _localHeadsNote("couldn't start "+headName+"'s head: "+(e&&e.message?e.message:e)); try{ await port.close(); }catch(_e){} return; }
  if(LOCAL_DRIVERS[headName]){ try{ await LOCAL_DRIVERS[headName].close(); }catch(_e){} }
  LOCAL_DRIVERS[headName]=drv;
  if(window.onLocalHeadsChanged) window.onLocalHeadsChanged();
}
async function disconnectHead(headName){
  var drv=LOCAL_DRIVERS[headName]; if(!drv) return;
  LOCAL_DRIVERS[headName]=null;
  try{ await drv.close(); }catch(e){}
  if(window.onLocalHeadsChanged) window.onLocalHeadsChanged();
}
function testNod(headName){ var drv=LOCAL_DRIVERS[headName]; if(drv) drv.nod(); }

// Lip dispatch used by duet + chat: returns true if a locally-connected head
// handled it (the caller then skips the PC-server POST).
function localHeadLip(headName, frames){ var d=LOCAL_DRIVERS[headName]; if(!d) return false; d.playLipSequence(frames); return true; }
function localHeadLipStop(headName){ var d=LOCAL_DRIVERS[headName]; if(!d) return false; d.lipStop(); return true; }
// Movement/test verbs used by the calibration page. Returns true if handled
// locally (skip the server); false for persistence/read verbs (hit the server).
function localHeadControl(headName, url, body){
  var d=LOCAL_DRIVERS[headName]; if(!d) return false; body=body||{};
  if(url==='/head/move'){ d.move(body.motor, body.pos, body.speed!=null?body.speed:7); return true; }
  if(url==='/head/action'){ d.action(body.action, body.times); return true; }
  if(url==='/head/eye-color'){ d.eyeColour(body.r||0, body.g||0, body.b||0); return true; }
  if(url==='/head/lip-test'){ d.lipTest(); return true; }
  if(url==='/head/lip-sweep'){ d.lipSweep(); return true; }
  if(url==='/head/lip-relax'){ d.lipRelax(); return true; }
  if(url==='/head/reset'){ d.reset(); return true; }
  if(url==='/head/demo'){ d.nodYes(2); return true; }
  if(url==='/head/expression'){ d.applyExpression(body.name); return true; }
  return false;
}
window.addEventListener('beforeunload', function(){ try{ for(var k in LOCAL_DRIVERS){ if(LOCAL_DRIVERS[k]) LOCAL_DRIVERS[k].lipStop(); } }catch(e){} });
"""

HEADS_HTML = """
<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Robot Heads &mdash; Setup</title>
<link rel="stylesheet" href="/assets/blue.css">
<script src="/assets/blue.js" defer></script>
<style>
 :root{ --cream:#faf8f4; --paper:#ffffff; --ink:#1a2e1a; --forest:#4a6b4a;
   --sage:#8fae8f; --slate:#64748b; --blue:#3b82f6; --gold:#d4af37;
   --line:#e3e0d8; --shadow:0 1px 3px rgba(0,0,0,.06); }
 body{font-family:-apple-system,'Segoe UI',sans-serif;background:var(--cream);color:var(--ink);max-width:780px;margin:0 auto;padding:28px 20px;line-height:1.55}
 h1{font-size:1.55em;margin-bottom:4px}
 p.sub{color:var(--slate);margin-bottom:18px;font-size:.95em}
 table{width:100%;border-collapse:collapse;margin:14px 0;font-size:.92em}
 th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
 th{font-size:.72em;text-transform:uppercase;letter-spacing:.08em;color:var(--forest)}
 .ok{color:#2e7d32;font-weight:600}.no{color:#9aa0a6}
 .pill{display:inline-block;padding:2px 9px;border-radius:11px;font-size:.8em}
 .pill.blue{background:#e3f0ff;color:#1b63b0}.pill.hexia{background:#f1e6fb;color:#7a3fb0}
 button{padding:6px 11px;border:1px solid var(--line);border-radius:7px;background:var(--paper);cursor:pointer;font:inherit;font-size:.88em;margin:2px 6px 2px 0;color:var(--ink)}
 button:hover{background:var(--mg-glass2,#f3f0e9)}button:disabled{opacity:.4;cursor:default}
 button.primary{background:#1a2e1a;color:#fff;border-color:#1a2e1a}
 #msg{margin:12px 0;padding:10px 12px;border-radius:8px;display:none}
 #msg.show{display:block}
 #msg.good{background:#eaf5ea;color:#23611f}#msg.bad{background:#f7ece9;color:#7a2e22}
 code{background:#f0ede6;padding:1px 5px;border-radius:4px;font-size:.9em}
 /* Midnight: status colors and pills become glass tints. */
 :root:not([data-theme="light"]) .ok{color:#4ade80}
 :root:not([data-theme="light"]) .no{color:var(--slate)}
 :root:not([data-theme="light"]) .pill.blue{background:rgba(61,169,252,.14);color:#7fc4ff}
 :root:not([data-theme="light"]) .pill.hexia{background:rgba(176,108,240,.14);color:#c9a1f5}
 :root:not([data-theme="light"]) #msg.good{background:rgba(74,222,128,.12);color:#4ade80}
 :root:not([data-theme="light"]) #msg.bad{background:rgba(248,113,113,.12);color:#f87171}
</style></head><body>
<h1>Robot Heads</h1>
<p class="sub">Blue and Hexia each drive their own Ohbot board over USB. Plug a board in, click <b>Refresh</b>, then assign it. Assignments are pinned by the board's USB serial number, so they survive reboots and COM-port renumbering. The Ohbot desktop app must be closed (it holds the port).</p>
<div id="msg"></div>
<button class="primary" id="refresh">Refresh</button>
<table><thead><tr><th>Port</th><th>USB serial</th><th>Ohbot?</th><th>Assigned&nbsp;to</th><th>Actions</th></tr></thead><tbody id="rows"></tbody></table>
<p class="sub">Tip: a board showing <b>Ohbot? &#10007;</b> that you know is a robot usually means the port is busy &mdash; close the Ohbot app (or whatever is holding it) and Refresh. A board with no USB serial can't be pinned.</p>
<script>
function show(t, good){ const m=document.getElementById('msg'); m.textContent=t; m.className='show '+(good?'good':'bad'); }
async function load(){
  let d;
  try { d = await (await fetch('/heads/detect')).json(); }
  catch(e){ return show('Could not read boards: '+e, false); }
  const rows = document.getElementById('rows'); rows.innerHTML='';
  const boards = d.boards||[];
  if(!boards.length){ rows.innerHTML='<tr><td colspan="5" class="no">No serial boards found. Plug one in and Refresh.</td></tr>'; return; }
  boards.forEach(b=>{
    const tr=document.createElement('tr');
    const assigned = b.held_by
       ? '<span class="pill '+b.held_by+'">'+b.held_by+' (live)</span>'
       : (b.assigned_to ? '<span class="pill '+b.assigned_to+'">'+b.assigned_to+'</span>' : '<span class="no">&mdash;</span>');
    const okmark = b.ohbot_compatible ? '<span class="ok">&#10003;</span>' : '<span class="no">&#10007;</span>';
    tr.innerHTML =
      '<td><code>'+b.device+'</code><br><span class="no">'+(b.description||'')+'</span></td>'+
      '<td>'+(b.serial_number?('<code>'+b.serial_number+'</code>'):'<span class="no">none</span>')+'</td>'+
      '<td>'+okmark+'</td>'+
      '<td>'+assigned+'</td>'+
      '<td class="acts"></td>';
    const acts = tr.querySelector('.acts');
    ['blue','hexia'].forEach(role=>{
      const btn=document.createElement('button');
      btn.textContent='\\u2192 '+role.charAt(0).toUpperCase()+role.slice(1);
      btn.disabled = !b.serial_number;
      btn.addEventListener('click', ()=>assign(b.serial_number, role));
      acts.appendChild(btn);
    });
    rows.appendChild(tr);
  });
}
async function assign(serial, role){
  if(!serial){ return show("That board has no USB serial number, so it can't be pinned.", false); }
  show('Assigning to '+role+'\\u2026', true);
  try{
    const d = await (await fetch('/heads/assign',{method:'POST',headers:{'Content-Type':'application/json'},
                     body:JSON.stringify({role:role, serial_number:serial})})).json();
    if(d.ok){ show(role.charAt(0).toUpperCase()+role.slice(1)+' assigned '+(d.available?'and connected \\u2713':'(board not responding \\u2014 is the Ohbot app closed?)')+'.', !!d.available); }
    else { show('Failed: '+(d.error||'unknown'), false); }
  }catch(e){ show('Request failed: '+e, false); }
  load();
}
document.getElementById('refresh').addEventListener('click', load);
load();
</script></body></html>
"""
