"""Extracted verbatim from bluetools.py (see blue/server/pages).

Do not import bluetools here; this module is pure data.
"""

CHAT_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>Chat with {{ robot_name }}</title>
    <link rel="stylesheet" href="/assets/blue.css">
    <script src="/assets/blue.js" defer></script>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Playfair+Display:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --cream: #faf8f4; --paper: #ffffff; --ink: #1a2e1a; --forest: #4a6b4a;
            --sage: #8fae8f; --slate: #64748b; --blue: #3b82f6; --gold: #d4af37;
            --line: rgba(143,174,143,0.32); --shadow: 0 8px 24px rgba(26,46,26,0.06);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body { height: 100%; }
        body {
            font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--cream); color: var(--ink); line-height: 1.55;
            display: flex; justify-content: center; padding: 32px 20px;
        }
        .container {
            width: 100%; max-width: 820px; height: calc(100vh - 64px);
            background: var(--paper); border: 1px solid var(--line); border-radius: 12px;
            box-shadow: var(--shadow); display: flex; flex-direction: column; overflow: hidden;
        }
        /* Phone: full-screen chat, input bar above the URL bar (100dvh).
           The input row REFLOWS: icon buttons get their own row, and the
           textarea + Send share a full-width row below — on an iPhone the
           old single row squeezed the textarea to nothing. */
        @media (max-width: 640px) {
            body { padding: 0; }
            .container { height: 100dvh; max-width: 100%; border: none; border-radius: 0; }
            .header { padding: 10px 14px 8px; }
            .header::before { width: 40px; height: 2px; margin-bottom: 8px; }
            .header h1 { font-size: 1.22em; }
            .header p { font-size: 0.85em; }
            .navlinks { flex-wrap: nowrap; overflow-x: auto; -webkit-overflow-scrolling: touch;
                        scrollbar-width: none; padding-bottom: 2px; }
            .navlinks::-webkit-scrollbar { display: none; }
            .messages { padding: 14px; gap: 14px; }
            .row { max-width: 92%; }
            .composer { padding: 10px 10px calc(12px + env(safe-area-inset-bottom)); }
            .input-bar { flex-wrap: wrap; gap: 8px; }
            .iconbtn { width: 42px; height: 42px; font-size: 1.05em; }
            .iconbtn svg { width: 20px; height: 20px; }
            /* iOS zooms the page on focus when an input's font is < 16px. */
            textarea { order: 10; flex: 1 1 calc(100% - 90px); font-size: 16px;
                       min-height: 44px; max-height: 120px; padding: 11px 12px; }
            .sendbtn { order: 11; height: 44px; padding: 0 16px; }
            .hint { display: none; }
            .cam-card { max-width: 100%; }
            .voice-card { max-height: 82vh; }
        }
        .header { padding: 24px 30px 20px; border-bottom: 1px solid var(--line); }
        .header::before {
            content: ""; display: block; width: 56px; height: 3px;
            background: linear-gradient(90deg, var(--gold), var(--blue)); margin-bottom: 14px;
        }
        .header h1 {
            font-family: 'Playfair Display', Georgia, serif; font-weight: 700;
            font-size: 1.7em; color: var(--ink); letter-spacing: -0.01em;
        }
        .header p { color: var(--slate); font-size: 0.95em; margin-top: 4px; }
        .header a { color: var(--forest); text-decoration: none; font-weight: 500; }
        .header a:hover { color: var(--ink); text-decoration: underline; }
        .messages { flex: 1 1 auto; overflow-y: auto; padding: 28px 30px; display: flex; flex-direction: column; gap: 18px; }
        .row { display: flex; flex-direction: column; max-width: 80%; }
        .row.user { align-self: flex-end; align-items: flex-end; }
        .row.blue { align-self: flex-start; align-items: flex-start; }
        .who {
            font-family: 'IBM Plex Mono', monospace; font-size: 0.68em; text-transform: uppercase;
            letter-spacing: 0.12em; color: var(--slate); margin-bottom: 5px;
        }
        .bubble { padding: 13px 17px; border-radius: 12px; font-size: 0.98em; white-space: pre-wrap; word-wrap: break-word; }
        .row.user .bubble { background: var(--ink); color: #fff; border-bottom-right-radius: 4px; }
        .row.blue .bubble { background: var(--cream); border: 1px solid var(--line); color: var(--ink); border-bottom-left-radius: 4px; }
        .bubble .att {
            display: inline-block; margin-top: 8px; font-family: 'IBM Plex Mono', monospace;
            font-size: 0.78em; opacity: 0.85;
        }
        .row.user .bubble .att { color: #d9e6d9; }
        .empty { color: var(--slate); text-align: center; margin: auto; max-width: 380px; }
        .empty .big { font-family: 'Playfair Display', Georgia, serif; font-size: 1.3em; color: var(--ink); margin-bottom: 8px; }
        .composer { border-top: 1px solid var(--line); padding: 16px 22px 20px; background: var(--paper); }
        .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
        .chip {
            display: inline-flex; align-items: center; gap: 8px; background: var(--cream);
            border: 1px solid var(--sage); border-radius: 6px; padding: 5px 10px;
            font-family: 'IBM Plex Mono', monospace; font-size: 0.78em; color: var(--forest);
        }
        .chip.err { border-color: #e2c4be; color: #7a2e22; background: #f7ece9; }
        .chip button { background: none; border: none; color: inherit; cursor: pointer; font-size: 1.1em; line-height: 1; padding: 0; }
        .input-bar { display: flex; gap: 10px; align-items: flex-end; }
        textarea {
            flex: 1; resize: none; min-height: 48px; max-height: 180px; padding: 13px 15px;
            border: 1px solid var(--sage); border-radius: 8px; font-family: inherit; font-size: 1em;
            color: var(--ink); background: var(--paper); line-height: 1.5;
        }
        textarea:focus { outline: none; border-color: var(--forest); }
        .iconbtn {
            flex-shrink: 0; width: 48px; height: 48px; border-radius: 8px; cursor: pointer;
            border: 1px solid var(--sage); background: var(--paper); color: var(--forest);
            font-size: 1.2em; transition: background 0.2s, border-color 0.2s;
        }
        .iconbtn:hover { background: var(--cream); border-color: var(--forest); }
        .iconbtn svg { width: 22px; height: 22px; stroke: currentColor; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; vertical-align: middle; }
        .iconbtn.active { background: var(--forest); border-color: var(--forest); color: #fff; }
        .hf-status { margin-top: 10px; font-family: 'IBM Plex Mono', monospace; font-size: 0.78em; color: var(--forest); text-align: center; display: flex; align-items: center; justify-content: center; gap: 8px; }
        .hf-status::before { content: ''; width: 8px; height: 8px; border-radius: 50%; background: var(--forest); display: inline-block; }
        .hf-status.voicing::before { background: #e9534e; animation: hf-pulse 0.9s infinite; }
        .hf-status.thinking::before { background: #d4af37; }
        .hf-status.armed::before { background: #3b82f6; }
        @keyframes hf-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        .hf-mode-btn { display: block; margin: 6px auto 0; background: none; border: 1px solid var(--sage); color: var(--forest); border-radius: 14px; padding: 4px 12px; font-family: 'IBM Plex Mono', monospace; font-size: 0.72em; cursor: pointer; }
        .hf-mode-btn:hover { background: var(--cream); }
        .micbtn { transition: background 0.15s, border-color 0.15s, transform 0.15s; }
        .micbtn.listening { background: #e9534e; border-color: #e9534e; color: #fff; transform: scale(1.08); }
        .micbtn.big { width: 60px; height: 60px; }
        .micbtn.big svg { width: 28px; height: 28px; }
        .sendbtn {
            flex-shrink: 0; height: 48px; padding: 0 24px; border-radius: 8px; border: none;
            background: var(--ink); color: #fff; font-weight: 500; font-size: 0.95em; cursor: pointer;
            transition: background 0.2s;
        }
        .sendbtn:hover:not(:disabled) { background: var(--forest); }
        .sendbtn:disabled { background: #c7cdc5; cursor: not-allowed; }
        .typing { font-family: 'IBM Plex Mono', monospace; font-size: 0.8em; color: var(--slate); }
        .hint { font-family: 'IBM Plex Mono', monospace; font-size: 0.72em; color: var(--slate); margin-top: 8px; }
        .voice-panel { position: fixed; top: 0; right: 0; bottom: 0; left: 0; background: rgba(26,46,26,0.45);
                       display: flex; align-items: center; justify-content: center; padding: 20px; z-index: 50; }
        .voice-card { background: var(--paper); border: 1px solid var(--line); border-radius: 12px; box-shadow: var(--shadow);
                      width: 100%; max-width: 380px; max-height: 72vh; display: flex; flex-direction: column; overflow: hidden; }
        .voice-head { display: flex; align-items: center; justify-content: space-between; padding: 15px 18px;
                      border-bottom: 1px solid var(--line); font-family: 'Playfair Display', Georgia, serif; font-size: 1.15em; color: var(--ink); }
        .voice-head button { background: none; border: none; font-size: 1.6em; line-height: 1; color: var(--slate); cursor: pointer; padding: 0 4px; }
        .voice-sub { padding: 11px 18px 2px; color: var(--slate); font-size: 0.82em; }
        .voice-list { overflow-y: auto; padding: 10px; }
        .voice-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; text-align: left;
                     background: var(--cream); border: 1px solid var(--line); border-radius: 8px; padding: 13px 14px; margin: 6px 0;
                     cursor: pointer; font-family: inherit; font-size: 0.96em; color: var(--ink); }
        .voice-row.sel { border-color: var(--forest); background: #eef4ee; }
        .voice-row .vn { font-weight: 500; }
        .voice-row.sel .vn:after { content: ' \2713'; color: var(--forest); }
        .voice-row .vl { font-family: 'IBM Plex Mono', monospace; font-size: 0.72em; color: var(--slate); white-space: nowrap; }
        .voice-empty { padding: 18px; color: var(--slate); text-align: center; }
        .lang-row { display: flex; flex-wrap: wrap; gap: 6px; padding: 6px 18px 10px; border-bottom: 1px solid var(--line); }
        .lang-chip { border: 1px solid var(--line); background: var(--paper); border-radius: 16px; padding: 5px 12px; font-size: 0.82em; cursor: pointer; }
        .lang-chip.sel { border-color: var(--forest); background: #eef4ee; font-weight: 600; }
        /* ---- Context & focus panel (document picker + location override) ---- */
        .ctx-place { display: flex; gap: 6px; padding: 4px 18px 6px; }
        .ctx-place input { flex: 1; min-width: 0; border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; font-family: inherit; font-size: 0.92em; }
        .ctx-btn { border: 1px solid var(--forest); background: var(--forest); color: #fff; border-radius: 8px; padding: 7px 12px; font-size: 0.85em; cursor: pointer; white-space: nowrap; }
        .ctx-btn.ghost { background: var(--paper); color: var(--slate); border-color: var(--line); }
        .ctx-place-now { padding: 0 18px 6px; color: var(--slate); font-size: 0.8em; min-height: 1em; }
        .ctx-list { overflow-y: auto; padding: 4px 10px; max-height: 38vh; }
        .ctx-folder { font-family: 'IBM Plex Mono', monospace; font-size: 0.72em; color: var(--slate); text-transform: uppercase; letter-spacing: 0.04em; padding: 10px 6px 2px; display: block; }
        label.ctx-folder { cursor: pointer; }
        .ctx-item { display: flex; align-items: flex-start; gap: 10px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; margin: 4px 0; background: var(--cream); cursor: pointer; }
        .ctx-item.sel { border-color: var(--forest); background: #eef4ee; }
        .ctx-item input, .ctx-folder input { margin-top: 3px; flex: none; }
        .ctx-item .ci-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
        .ctx-item .ci-name { font-weight: 500; color: var(--ink); font-size: 0.92em; word-break: break-word; }
        .ctx-item .ci-prev { color: var(--slate); font-size: 0.78em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .ctx-foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 18px; border-top: 1px solid var(--line); }
        .ctx-foot #ctxCount { color: var(--slate); font-size: 0.82em; }
        /* ---- Kid mode (Vilda's iPad): bigger, warmer, simpler ---- */
        body.kid { background: linear-gradient(160deg, #fff7ed 0%, #eef6ff 100%); }
        body.kid .container { max-width: 760px; }
        body.kid .header { text-align: center; }
        body.kid .header h1 { font-size: 2.1em; display: inline-flex; align-items: center; gap: 12px; }
        body.kid .header h1 .robot { width: 46px; height: 46px; color: #3b82f6; }
        body.kid .header p { font-size: 1.08em; color: var(--forest); }
        body.kid .messages { font-size: 1.12em; gap: 22px; }
        body.kid .row { max-width: 92%; }
        body.kid .bubble { font-size: 1.15em; border-radius: 20px; padding: 16px 20px; line-height: 1.5; }
        body.kid .row.blue .bubble { background: #fffdf7; border-color: #e7dcc2; }
        body.kid .empty .big { font-size: 1.8em; }
        body.kid textarea { font-size: 1.12em; border-radius: 14px; }
        body.kid #attachBtn { display: none; }
        body.kid .iconbtn { width: 54px; height: 54px; }
        body.kid .micbtn.big { width: 84px; height: 84px; border-width: 2px; }
        body.kid .micbtn.big svg { width: 40px; height: 40px; }
        body.kid .sendbtn { font-size: 1.05em; border-radius: 14px; }
        body.kid .hint { font-size: 0.92em; text-align: center; }
        /* sweet touches */
        body.kid { background: linear-gradient(160deg, #fff1f6 0%, #eef6ff 100%); }
        body.kid .header h1 { color: #c0578f; }
        body.kid .header h1 .robot { color: #ff7eb3; }
        body.kid .empty .big { color: #c0578f; }
        body.kid .row.user .bubble { background: #bfe3ff; color: #143a52; border-bottom-right-radius: 6px; }
        body.kid .row.blue .bubble { box-shadow: 0 2px 9px rgba(192,87,143,0.10); }
        body.kid .composer { border-top: 2px solid #ffe1ec; background: #fffdfb; }
        body.kid .sendbtn { background: #ff7eb3; }
        body.kid .sendbtn:hover:not(:disabled) { background: #f3669f; }
        @keyframes kidbob { 0%, 100% { transform: translateY(0) rotate(-3deg); } 50% { transform: translateY(-4px) rotate(3deg); } }
        body.kid .header h1 .robot { animation: kidbob 2.8s ease-in-out infinite; }
        @keyframes kidpulse { 0% { box-shadow: 0 0 0 0 rgba(255,126,179,0.40); } 70% { box-shadow: 0 0 0 16px rgba(255,126,179,0); } 100% { box-shadow: 0 0 0 0 rgba(255,126,179,0); } }
        body.kid .micbtn.big:not(.listening) { animation: kidpulse 2.4s infinite; }

        /* ---- On-screen Blue face (kid mode): a friend Vilda can SEE react. ----
           The physical robot stays still for her, so this IS "her" Blue: it
           blinks + bobs when idle, perks up when she talks, and moves its mouth
           while Blue reads his reply aloud. Plain HTML/CSS, iOS-12 safe. */
        .blue-face { width: 150px; margin: 8px auto 4px; animation: bfBob 3.4s ease-in-out infinite; }
        .bf-antenna { position: relative; width: 3px; height: 16px; margin: 0 auto -2px; background: #9cc4ff; border-radius: 3px; }
        .bf-dot { position: absolute; top: -7px; left: 50%; width: 11px; height: 11px; margin-left: -5.5px; background: #ffd24a; border-radius: 50%; box-shadow: 0 0 7px rgba(255,210,74,0.85); }
        .bf-head { position: relative; width: 150px; height: 128px; margin: 0 auto; border-radius: 30px; background: linear-gradient(160deg, #6cb0ff 0%, #3b82f6 100%); box-shadow: 0 9px 22px rgba(59,130,246,0.32), inset 0 -6px 14px rgba(0,0,0,0.08); transition: transform .2s; }
        .bf-ear { position: absolute; top: 47px; width: 9px; height: 26px; background: #9cc4ff; border-radius: 6px; }
        .bf-ear.l { left: -7px; } .bf-ear.r { right: -7px; }
        .bf-eye { position: absolute; top: 40px; width: 30px; height: 30px; background: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center; transform-origin: center; animation: bfBlink 4.6s infinite; box-shadow: inset 0 2px 3px rgba(0,0,0,0.08); }
        .bf-eye.l { left: 30px; } .bf-eye.r { right: 30px; }
        .bf-pupil { width: 14px; height: 14px; background: #15394d; border-radius: 50%; transition: transform .2s; }
        .bf-cheek { position: absolute; top: 75px; width: 16px; height: 9px; background: #ff9ec4; opacity: .7; border-radius: 50%; }
        .bf-cheek.l { left: 31px; } .bf-cheek.r { right: 31px; }
        .bf-mouth { position: absolute; left: 50%; top: 89px; width: 40px; height: 11px; margin-left: -20px; background: #15394d; border-radius: 4px 4px 20px 20px; transition: height .12s, width .12s, border-radius .12s, margin-left .12s; }
        @keyframes bfBob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-5px); } }
        @keyframes bfBlink { 0%, 90%, 100% { transform: scaleY(1); } 95% { transform: scaleY(0.12); } }
        @keyframes bfTalk { 0% { height: 9px; border-radius: 4px 4px 16px 16px; } 50% { height: 22px; border-radius: 50%; } 100% { height: 9px; border-radius: 4px 4px 16px 16px; } }
        @keyframes bfPulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(255,126,179,0.55); } 50% { box-shadow: 0 0 0 9px rgba(255,126,179,0); } }
        .blue-face.talking .bf-mouth { animation: bfTalk .26s infinite; }
        .blue-face.listening .bf-dot { background: #ff7eb3; animation: bfPulse 1.2s infinite; }
        .blue-face.thinking .bf-pupil { transform: translateY(-3px); }
        .blue-face.thinking .bf-mouth { width: 16px; margin-left: -8px; height: 8px; border-radius: 8px; }
        .blue-face.curious .bf-head { transform: rotate(-5deg); }
        .blue-face.curious .bf-mouth { width: 16px; height: 16px; margin-left: -8px; border-radius: 50%; }

        /* ---- Blue's eyes: the iPad camera preview (kid mode) ---- */
        #eyeBtn.active { background: #ff7eb3; border-color: #ff7eb3; color: #fff; }
        /* Small floating preview (picture-in-picture) so the chat text below it
           stays fully visible. Sits just above the composer, out of the layout. */
        .eye-panel { display: none; position: fixed; right: 12px; bottom: 124px; width: 118px; z-index: 60; }
        .eye-panel.on { display: block; }
        .eye-panel video { width: 100%; border-radius: 14px; border: 2px solid #ff7eb3; background: #000; display: block; transform: scaleX(-1); box-shadow: 0 4px 16px rgba(0,0,0,0.22); }
        .eye-panel.rear video { transform: none; }
        .eye-panel .eye-cap { display: none; }
        .eye-tools { position: absolute; top: 5px; right: 5px; display: flex; gap: 4px; }
        .eye-tools button { width: 26px; height: 26px; border-radius: 50%; border: none; background: rgba(0,0,0,0.55); color: #fff; font-size: 0.95em; line-height: 1; cursor: pointer; }
        .eye-tools button:active { background: rgba(0,0,0,0.78); }

        /* ---- Robot camera live preview ("see through my eyes") ---- */
        .navlinks { display: flex; flex-wrap: wrap; gap: 4px 18px; margin-top: 6px; font-size: 0.92em; }
        .navlinks a { color: var(--forest); text-decoration: none; font-weight: 500; white-space: nowrap; }
        .navlinks a:hover { color: var(--ink); text-decoration: underline; }
        #camBtn.active { background: var(--forest); border-color: var(--forest); color: #fff; }
        .cam-panel { position: fixed; top: 0; right: 0; bottom: 0; left: 0; background: rgba(26,46,26,0.45);
                     display: flex; align-items: center; justify-content: center; padding: 14px; z-index: 70; }
        .cam-card { background: var(--paper); border: 1px solid var(--line); border-radius: 12px; box-shadow: var(--shadow);
                    width: 100%; max-width: 560px; display: flex; flex-direction: column; overflow: hidden; }
        .cam-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px;
                    border-bottom: 1px solid var(--line); font-family: 'Playfair Display', Georgia, serif; font-size: 1.1em; color: var(--ink); }
        .cam-head button { background: none; border: none; font-size: 1.6em; line-height: 1; color: var(--slate); cursor: pointer; padding: 0 4px; }
        .cam-card img { width: 100%; display: block; background: #000; min-height: 180px; max-height: 52vh; object-fit: contain; }
        .cam-controls { display: flex; align-items: center; justify-content: space-evenly; gap: 12px; padding: 12px 10px 6px; flex-wrap: wrap; }
        .cam-pad { display: flex; flex-direction: column; align-items: center; gap: 4px; }
        .cam-pad > div { display: flex; gap: 4px; }
        .cam-pad button, .cam-zoom button { width: 44px; height: 44px; border-radius: 9px; border: 1px solid var(--sage);
                    background: var(--paper); color: var(--forest); font-size: 1.05em; cursor: pointer; }
        .cam-pad button:active, .cam-zoom button:active { background: var(--cream); border-color: var(--forest); }
        .cam-zoom { display: flex; align-items: center; gap: 10px; }
        .cam-zoom span { font-family: 'IBM Plex Mono', monospace; min-width: 48px; text-align: center; color: var(--ink); }
        .cam-zoom button { font-size: 1.4em; }
        .cam-sub { padding: 4px 14px 12px; color: var(--slate); font-size: 0.8em; text-align: center; }
    </style>
</head>
<body{% if kid %} class="kid"{% endif %}>
    <div class="container">
        <div class="header">
            {% if kid %}
            <h1><svg class="robot" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="8" width="14" height="11" rx="3"/><path d="M12 5.4v2.6"/><circle cx="12" cy="4" r="1.4"/><circle cx="9.6" cy="13" r="1.1"/><circle cx="14.4" cy="13" r="1.1"/><path d="M9.8 16.3h4.4"/><path d="M5 12H3.4M19 12h1.6"/></svg> Hi! I'm {{ robot_name }}</h1>
            <p>I'm so happy you're here! Tap the big mic and let's talk. &#128153;</p>
            {% else %}
            <h1>Chat with {{ robot_name }}</h1>
            <p>Type to talk with {{ robot_name }}, and attach images or documents to share.</p>
            <div class="navlinks"><a href="/">&larr; Home</a>{% if is_bluej %}<a href="/bluej/continuity">Continuity</a>{% endif %}<a href="/duet">Duet</a><a href="/calendar">Calendar</a><a href="/contacts">Contacts</a><a href="/visual">Visual Memory</a><a href="/documents">Documents</a></div>
            {% endif %}
        </div>
        {% if kid %}
        <div class="blue-face" id="blueFace" aria-hidden="true">
            <div class="bf-antenna"><span class="bf-dot"></span></div>
            <div class="bf-head">
                <span class="bf-ear l"></span><span class="bf-ear r"></span>
                <div class="bf-eye l"><span class="bf-pupil"></span></div>
                <div class="bf-eye r"><span class="bf-pupil"></span></div>
                <span class="bf-cheek l"></span><span class="bf-cheek r"></span>
                <div class="bf-mouth"></div>
            </div>
        </div>
        {% endif %}
        <div class="messages" id="messages">
            <div class="empty" id="empty">
                {% if kid %}
                <div class="big">Hi Vilda! &#128153;</div>
                <div>I'm so happy to see you! Tap the big microphone and let's chat.</div>
                {% else %}
                <div class="big">Say hello to {{ robot_name }}</div>
                <div>Ask {{ robot_name }} anything, or attach a photo and ask what he sees. Attach a document and ask him about it.</div>
                {% endif %}
            </div>
        </div>
        <div class="composer">
            <div class="chips" id="chips"></div>
            <div class="input-bar">
                <input type="file" id="fileInput" multiple style="display:none"
                       accept=".png,.jpg,.jpeg,.gif,.bmp,.webp,.tiff,.pdf,.doc,.docx,.txt,.md,.csv,.json,.xml,.html,.rtf,.pptx,.xlsx">
                <button class="iconbtn" id="attachBtn" title="Attach files" aria-label="Attach files">+</button>
                <button class="iconbtn micbtn" id="micBtn" title="Tap and talk to {{ robot_name }}" aria-label="Talk to {{ robot_name }}">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3z"/><path d="M6 11a6 6 0 0 0 12 0"/><path d="M12 17v4"/></svg>
                </button>
                {% if not kid %}
                <button class="iconbtn" id="camBtn" title="See through {{ robot_name }}'s camera" aria-label="Live camera preview" aria-pressed="false">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h3.2L9 5.5h6L16.8 8H20a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="3.4"/></svg>
                </button>
                <button class="iconbtn" id="researchBtn" title="Research mode: {{ robot_name }} searches the web before answering" aria-label="Toggle web research" aria-pressed="false">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="M15.8 15.8 21 21"/></svg>
                </button>
                <button class="iconbtn" id="wikiBtn" title="Consult Wikipedia: {{ robot_name }} reads the encyclopedia on your topic before answering" aria-label="Toggle Wikipedia consult" aria-pressed="false">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 6.5C10.5 5 8 4.5 4.5 5v13c3.5-.5 6 0 7.5 1.5 1.5-1.5 4-2 7.5-1.5V5C16 4.5 13.5 5 12 6.5z"/><path d="M12 6.5v13"/></svg>
                </button>
                <button class="iconbtn" id="contextBtn" title="Focus {{ robot_name }} on specific library documents" aria-label="Context and document focus" aria-pressed="false">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 3 8l9 5 9-5-9-5z"/><path d="M3 13l9 5 9-5"/></svg>
                </button>
                {% endif %}
                {% if kid %}
                <button class="iconbtn" id="eyeBtn" title="Let Blue look through the camera" aria-label="Blue's eyes" aria-pressed="false">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>
                </button>
                {% endif %}
                <button class="iconbtn" id="hfBtn" title="Hands-free: say 'Blue' to start" aria-label="Hands-free listening" aria-pressed="false">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 10c0-3 2.5-5.5 5.5-5.5s5.5 2.5 5.5 5.5v3.5a3 3 0 0 1-3 3h-1"/><path d="M6.5 10v2.5a3 3 0 0 0 2 2.8"/><path d="M9.5 18c.7.8 1.7 1.4 3 1.4"/></svg>
                </button>
                <textarea id="input" placeholder="Message {{ robot_name }}..." rows="1"></textarea>
                <button class="iconbtn" id="voiceBtn" title="Choose {{ robot_name }}'s voice" aria-label="Choose {{ robot_name }}'s voice">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path d="M5.5 20c0-3.6 3-5.5 6.5-5.5s6.5 1.9 6.5 5.5"/></svg>
                </button>
                <button class="iconbtn" id="speakBtn" title="Blue reads his answers out loud" aria-label="Toggle spoken replies" aria-pressed="false">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M16 8a5 5 0 0 1 0 8"/></svg>
                </button>
                <button class="iconbtn" id="connHeadBtn" title="Drive {{ robot_name }}'s head from this device's USB-C port" aria-label="Connect a USB-C head" aria-pressed="false" style="display:none">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="2.5" width="6" height="7" rx="1.5"/><path d="M11 9.5v3"/><path d="M13 9.5v3"/><path d="M8 12.5h8v3.5a4 4 0 0 1-8 0z"/><path d="M12 20v2"/></svg>
                </button>
                <button class="sendbtn" id="sendBtn">Send</button>
            </div>
            {% if kid %}
            <div class="eye-panel" id="eyePanel">
                <video id="eyeVid" playsinline muted autoplay></video>
                <div class="eye-tools">
                    <button id="eyeFlip" title="Flip camera" aria-label="Flip camera">&#8635;</button>
                    <button id="eyeClose" title="Close Blue's eyes" aria-label="Close camera">&times;</button>
                </div>
                <div class="eye-cap">Tap the eye and I'll look! &#128064;</div>
            </div>
            <canvas id="eyeCanvas" style="display:none"></canvas>
            {% endif %}
            <div class="hint">Enter to send &middot; Shift+Enter for a new line</div>
            <div id="hfStatus" class="hf-status" style="display:none"></div>
            <button id="hfModeBtn" class="hf-mode-btn" style="display:none" type="button">Mode: say "Blue" first</button>
        </div>
    </div>

    <div class="voice-panel" id="voicePanel" style="display:none">
        <div class="voice-card">
            <div class="voice-head"><span>{{ robot_name }} &mdash; language &amp; voice</span><button id="voiceClose" aria-label="Close">&times;</button></div>
            <div class="voice-sub">Which language are we speaking? Auto means {{ robot_name }} guesses from each clip; picking one makes him hear and answer in it reliably.</div>
            <div class="lang-row" id="langRow"></div>
            <div class="voice-sub">Tap a voice to hear it. The one with a check mark is the one Blue uses.</div>
            <div class="voice-list" id="voiceList"></div>
        </div>
    </div>

    {% if not kid %}
    <div class="cam-panel" id="camPanel" style="display:none">
        <div class="cam-card">
            <div class="cam-head"><span>{{ robot_name }}'s camera &mdash; live</span><button id="camClose" aria-label="Close camera preview">&times;</button></div>
            <img id="camStream" alt="Live camera view">
            <div class="cam-controls">
                <div class="cam-pad" aria-label="Pan and tilt the camera">
                    <button data-look="up" title="Pan the camera up">&#9650;</button>
                    <div>
                        <button data-look="left" title="Pan the camera left">&#9664;</button>
                        <button data-look="center" title="Re-center the camera">&#8962;</button>
                        <button data-look="right" title="Pan the camera right">&#9654;</button>
                    </div>
                    <button data-look="down" title="Pan the camera down">&#9660;</button>
                </div>
                <div class="cam-zoom" aria-label="Camera zoom">
                    <button id="camZoomOut" title="Zoom out">&minus;</button>
                    <span id="camZoomVal">1&times;</span>
                    <button id="camZoomIn" title="Zoom in">+</button>
                </div>
            </div>
            <div class="cam-sub">The arrows pan the camera lens itself (it zooms to 2&times; first &mdash; panning moves the zoom window). Line up the view, then just ask &mdash; &ldquo;what do you see?&rdquo; captures exactly this.</div>
        </div>
    </div>
    {% endif %}

    {% if not kid %}
    <div class="voice-panel" id="contextPanel" style="display:none">
        <div class="voice-card">
            <div class="voice-head"><span>{{ robot_name }} &mdash; context &amp; focus</span><button id="contextClose" aria-label="Close">&times;</button></div>
            <div class="voice-sub">Where are we? {{ robot_name }} assumes you're home; set a place when you're somewhere else.</div>
            <div class="ctx-place">
                <input type="text" id="placeInput" placeholder="e.g. the cottage" autocomplete="off">
                <button class="ctx-btn" id="placeSet">Set</button>
                <button class="ctx-btn ghost" id="placeHome">Back home</button>
            </div>
            <div class="ctx-place-now" id="placeNow"></div>
            <div class="voice-sub">Focus documents &mdash; pick what {{ robot_name }} should treat as his authoritative knowledge for this chat. Nothing checked = his whole library.</div>
            <div class="ctx-list" id="ctxList"><div class="voice-empty">Loading your library&hellip;</div></div>
            <div class="ctx-foot">
                <span id="ctxCount">No documents focused</span>
                <button class="ctx-btn ghost" id="ctxClear">Clear</button>
            </div>
        </div>
    </div>
    {% endif %}

    <script src="/js/ohbot-heads.js"></script>
    <script>
        const messagesEl = document.getElementById('messages');
        const emptyEl = document.getElementById('empty');
        const inputEl = document.getElementById('input');
        const sendBtn = document.getElementById('sendBtn');
        const attachBtn = document.getElementById('attachBtn');
        const fileInput = document.getElementById('fileInput');
        const chipsEl = document.getElementById('chips');

        // On-screen Blue face (kid mode only — null elsewhere, so every call
        // below is a harmless no-op for Alex). Gives Vilda a Blue she can SEE
        // react, since the physical robot stays still for her. States:
        // listening / thinking / talking / curious; no class = calm idle smile
        // (it blinks and bobs on its own via CSS).
        const blueFace = document.getElementById('blueFace');
        function setFaceState(state) {
            if (!blueFace) return;
            blueFace.classList.remove('listening', 'thinking', 'talking', 'curious');
            if (state) blueFace.classList.add(state);
        }
        function faceCuriousBriefly() {
            if (!blueFace) return;
            setFaceState('curious');
            setTimeout(function () { if (blueFace.classList.contains('curious')) setFaceState(''); }, 1600);
        }

        // Identify this device so the server knows who's chatting (iPad => Vilda,
        // everything else => Alex). Done in the browser because a "desktop-mode"
        // iPad masquerades as a Mac in the User-Agent and is only distinguishable
        // here, via touch support (a real Mac reports zero touch points).
        function blueDeviceTag() {
            const ua = navigator.userAgent || '';
            const touch = (navigator.maxTouchPoints || 0) > 1;
            if (/iPad/.test(ua) || (/Macintosh/.test(ua) && touch)) return 'ipad';
            if (/iPhone|iPod/.test(ua)) return 'iphone';
            if (/Android/.test(ua)) return 'android';
            if (/Macintosh|Mac OS X/.test(ua)) return 'mac';
            if (/Windows/.test(ua)) return 'windows';
            return 'other';
        }

        // Conversation as sent to the API (role/content). Persona + memory are
        // applied server-side, so we only carry the user/assistant turns.
        let apiMessages = [];
        // Staged attachments for the NEXT message. Images are already staged in
        // Blue's vision queue server-side; docs carry their extracted text here.
        let pending = [];
        let busy = false;

        function esc(s) {
            const d = document.createElement('div');
            d.textContent = s == null ? '' : String(s);
            return d.innerHTML;
        }

        function addBubble(role, text, attachments) {
            if (emptyEl) emptyEl.style.display = 'none';
            const row = document.createElement('div');
            row.className = 'row ' + (role === 'user' ? 'user' : 'blue');
            let inner = '<div class="who">' + (role === 'user' ? 'You' : ROBOT.name) + '</div>';
            let body = esc(text);
            if (attachments && attachments.length) {
                body += attachments.map(a => '<span class="att">[' + esc(a.name) + ']</span>').join(' ');
            }
            inner += '<div class="bubble">' + body + '</div>';
            row.innerHTML = inner;
            messagesEl.appendChild(row);
            messagesEl.scrollTop = messagesEl.scrollHeight;
            return row;
        }

        function renderChips() {
            chipsEl.innerHTML = pending.map((a, i) => {
                if (a.kind === 'error') {
                    return '<span class="chip err">' + esc(a.name) + ' — ' + esc(a.error || 'unsupported') + '</span>';
                }
                const tag = a.kind === 'image' ? 'image' : 'doc';
                return '<span class="chip">' + esc(a.name) + ' <span style="opacity:.6">' + tag + '</span>'
                     + '<button data-i="' + i + '" title="Remove">&times;</button></span>';
            }).join('');
            chipsEl.querySelectorAll('button[data-i]').forEach(b => {
                b.addEventListener('click', () => { pending.splice(parseInt(b.dataset.i), 1); renderChips(); });
            });
        }

        attachBtn.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', async () => {
            if (!fileInput.files.length) return;
            const fd = new FormData();
            for (const f of fileInput.files) fd.append('files', f);
            fileInput.value = '';
            attachBtn.disabled = true;
            try {
                const res = await fetch('/chat/attach', { method: 'POST', body: fd });
                let data = null;
                try { data = await res.json(); } catch (_) { /* non-JSON (e.g. HTML error page) */ }
                if (data && data.attachments) {
                    data.attachments.forEach(a => pending.push(a));
                } else {
                    const msg = (data && data.error)
                        || (res.status === 413 ? 'file too large'
                            : ('upload failed (HTTP ' + res.status + ')'));
                    pending.push({ name: msg, kind: 'error', error: msg });
                }
                renderChips();
            } catch (e) {
                pending.push({ name: 'upload failed', kind: 'error', error: String(e) });
                renderChips();
            } finally {
                attachBtn.disabled = false;
            }
        });

        function autoGrow() {
            inputEl.style.height = 'auto';
            inputEl.style.height = Math.min(inputEl.scrollHeight, 180) + 'px';
        }
        inputEl.addEventListener('input', autoGrow);
        inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
        });
        sendBtn.addEventListener('click', send);

        // Set true right before a voice-originated send() so the server knows
        // to keep the reply short (spoken replies should be brief — and fewer
        // tokens = faster generation = Blue starts talking sooner). Consumed
        // (reset) inside send().
        let pendingVoice = false;

        async function send() {
            if (busy) return;
            primeAudio();
            const isVoiceTurn = pendingVoice; pendingVoice = false;
            const text = inputEl.value.trim();
            const atts = pending.slice();
            if (!text && !atts.length) return;

            // Build the content actually sent: user's text plus any extracted
            // document text (images are injected server-side from the queue).
            let sentContent = text;
            const docBlocks = atts.filter(a => a.kind === 'doc' && a.text)
                .map(a => '[Attached document: ' + a.name + ']\\n\"\"\"\\n' + a.text + '\\n\"\"\"');
            if (docBlocks.length) {
                sentContent = docBlocks.join('\\n\\n') + (text ? ('\\n\\n' + text) : '\\n\\nPlease take a look at the attached document.');
            }
            if (!sentContent) sentContent = 'What do you make of this?';

            addBubble('user', text || '(see attachment)', atts.filter(a => a.kind !== 'error'));
            apiMessages.push({ role: 'user', content: sentContent });

            inputEl.value = '';
            autoGrow();
            pending = [];
            renderChips();

            busy = true; sendBtn.disabled = true; sendBtn.textContent = '...';
            const thinking = addBubble('blue', '');
            thinking.querySelector('.bubble').innerHTML = '<span class="typing">' + ROBOT.name + (researchOn ? ' is researching…' : (wikiOn ? ' is checking Wikipedia…' : ' is thinking…')) + '</span>';
            setFaceState('thinking');

            try {
                // If Blue's eyes (iPad camera) are open, grab a fresh frame first
                // so he can see during THIS turn — not only when the eye is tapped.
                // No-op when the camera is closed or on Alex's page.
                if (window.__blueEyeGrab) { try { await window.__blueEyeGrab(); } catch (e) {} }
                const res = await fetch('/v1/chat/completions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Blue-Device': blueDeviceTag() },
                    body: JSON.stringify({ messages: apiMessages, voice: isVoiceTurn, robot: ROBOT.id,
                                           language: (LANG_MODE !== 'auto' ? LANG_MODE : ''),
                                           research: researchOn, wiki: wikiOn, focus: FOCUS })
                });
                const data = await res.json();
                let reply = '';
                try { reply = data.choices[0].message.content || ''; } catch (e) { reply = ''; }
                if (!reply) reply = 'Sorry, I didn\\'t catch that — could you try again?';
                thinking.querySelector('.bubble').textContent = reply;
                setFaceState('');
                speak(reply);
                messagesEl.scrollTop = messagesEl.scrollHeight;
                apiMessages.push({ role: 'assistant', content: reply });
            } catch (e) {
                thinking.querySelector('.bubble').textContent = 'I had trouble reaching my brain just now. Is the server running?';
                faceCuriousBriefly();
            } finally {
                busy = false; sendBtn.disabled = false; sendBtn.textContent = 'Send';
                inputEl.focus();
            }
        }

        // ===== Voice: Blue speaks aloud, and (over HTTPS) you can talk to him =====
        // Voice-first for Vilda's iPad: replies are read out loud and the mic is
        // big. The mic uses the browser's speech recognition, which Safari only
        // allows over a secure (https) connection — hence the Tailscale setup.
        // Which robot this page is — Blue (/chat) or Hexia (/hexia). Drives the
        // chat target, the accent colour, the spoken voice and which head moves.
        const ROBOT = {{ robot_json|safe }};
        try { if (ROBOT.accent) document.documentElement.style.setProperty('--blue', ROBOT.accent); } catch (e) {}
        const isVilda = blueDeviceTag() === 'ipad';
        let speakOn = isVilda;
        let audioPrimed = false;
        const micBtn = document.getElementById('micBtn');
        const speakBtn = document.getElementById('speakBtn');

        function primeAudio() {
            // iOS only lets speech start after a real tap; speaking an empty line
            // during the tap unlocks it for the automatic replies that follow.
            if (audioPrimed || !('speechSynthesis' in window)) return;
            try { window.speechSynthesis.speak(new SpeechSynthesisUtterance('')); audioPrimed = true; }
            catch (e) { /* no speech available */ }
        }

        // Pick a voice for the given language, preferring a male voice where one
        // exists (Blue is a man). Greek on iOS only ships a female voice.
        function pickVoice(lang) {
            const voices = (window.speechSynthesis && window.speechSynthesis.getVoices()) || [];
            // Blue prefers a male voice; Hexia (ROBOT.preferFemale) a female one.
            const malePrefs = {
                en: ['Daniel', 'Aaron', 'Arthur', 'Gordon', 'Rishi', 'Fred', 'Albert', 'Microsoft David', 'Microsoft Mark', 'Google UK English Male', 'Google US English'],
                fr: ['Thomas', 'Nicolas', 'Microsoft Claude', 'Microsoft Paul', 'Google fran\\u00e7ais'],
                ru: ['Yuri', 'Microsoft Pavel', 'Google \\u0440\\u0443\\u0441\\u0441\\u043a\\u0438\\u0439'],
                el: ['Melina', 'Microsoft Stefanos'],
                da: ['Magnus', 'Sara', 'Microsoft Helle']
            };
            const femalePrefs = {
                en: ['Samantha', 'Victoria', 'Karen', 'Moira', 'Tessa', 'Serena', 'Microsoft Zira', 'Google UK English Female', 'Google US English'],
                fr: ['Amelie', 'Audrey', 'Virginie', 'Aurelie', 'Microsoft Julie', 'Google fran\\u00e7ais'],
                ru: ['Milena', 'Katya', 'Microsoft Irina', 'Google \\u0440\\u0443\\u0441\\u0441\\u043a\\u0438\\u0439'],
                el: ['Melina', 'Microsoft Stefanos'],
                da: ['Sara', 'Microsoft Helle']
            };
            const prefs = (ROBOT && ROBOT.preferFemale) ? femalePrefs : malePrefs;
            const pl = prefs[lang] || prefs.en;
            for (let i = 0; i < pl.length; i++) {
                const v = voices.find(x => x.name === pl[i] || x.name.indexOf(pl[i]) === 0);
                if (v) return v;
            }
            const re = new RegExp('^' + (lang || 'en'), 'i');
            return voices.find(x => re.test(x.lang)) || voices.find(x => /^en/i.test(x.lang)) || null;
        }

        // Best-effort detection of Blue's reply language so we speak it with the
        // right voice: Cyrillic => Russian, Greek block => Greek; otherwise look
        // for French signals, else English.
        function detectLang(t) {
            const s = t || '';
            if (/[\\u0400-\\u04FF]/.test(s)) return 'ru';
            if (/[\\u0370-\\u03FF]/.test(s)) return 'el';
            // Danish uses æ ø å (Æ Ø Å) which French doesn't.
            if (/[\\u00e6\\u00f8\\u00e5\\u00c6\\u00d8\\u00c5]/.test(s)) return 'da';
            const daWords = /\\b(jeg|du|det|er|og|ikke|hej|tak|hvad|hvor|hvordan|ja|nej|kan|skal|har|vil|med|p\\u00e5)\\b/i;
            if (daWords.test(s)) return 'da';
            const accents = (s.match(/[\\u00e0\\u00e2\\u00e7\\u00e9\\u00e8\\u00ea\\u00eb\\u00ee\\u00ef\\u00f4\\u00f9\\u00fb\\u00fc\\u0153]/gi) || []).length;
            const frWords = /\\b(le|la|les|une|des|est|vous|je|tu|nous|bonjour|merci|oui|non|pour|avec|pas|bien|tres|aussi|aujourd)\\b/i;
            if (accents >= 2 || frWords.test(s)) return 'fr';
            return 'en';
        }

        function cleanForSpeech(t) {
            return (t || '')
                .replace(/https?:\\/\\/\\S+/g, ' a link ')
                // Square-bracket source tags ([Blue_Thoughts_2605.pdf], [1]) stay
                // visible in the chat text but are never read aloud (Alex, 2026-07-09).
                .replace(/\\[[^\\[\\]]{1,120}\\]/g, ' ')
                .replace(/[\\u{1F000}-\\u{1FFFF}\\u{2600}-\\u{27BF}]/gu, '')
                .replace(/[*_`#>~]/g, '')
                .replace(/\\s+/g, ' ')
                .trim();
        }

        // The voice Vilda picked (saved per-device), or null if none chosen.
        function chosenVoice() {
            let name = '';
            try { name = localStorage.getItem('blueVoiceName_' + ROBOT.id) || (ROBOT.id === 'blue' ? (localStorage.getItem('blueVoiceName') || '') : ''); } catch (e) {}
            if (!name) return null;
            const voices = (window.speechSynthesis && window.speechSynthesis.getVoices()) || [];
            for (let i = 0; i < voices.length; i++) { if (voices[i].name === name) return voices[i]; }
            return null;
        }

        // Build a timed mouth schedule from the reply text so the robot's jaw
        // moves during words and the mouth CLOSES during the gaps — including
        // longer pauses at commas and sentence ends. Each frame is
        // [openness 0-1, hold_seconds]. Sent once to /head/lip-seq; the server
        // plays it out (works on iOS 12 too, where speech boundary events don't
        // fire). Durations are an estimate of the TTS rhythm; onend stops it.
        function buildLipFrames(text, rate) {
            rate = rate || 1.0;
            const k = 1.0 / rate;                 // slower speech → longer holds
            const words = (text.match(/[^\\s]+/g) || []);
            const frames = [];
            const MS_PER_CHAR = 0.060;            // seconds of jaw motion per letter
            for (let wi = 0; wi < words.length; wi++) {
                const w = words[wi];
                const core = w.replace(/[^A-Za-z0-9\\u00C0-\\u024F\\u0370-\\u03FF\\u0400-\\u04FF]/g, '');
                const len = Math.max(1, core.length);
                let dur = Math.min(0.75, Math.max(0.14, len * MS_PER_CHAR)) * k;
                const moves = Math.max(1, Math.round(len / 3));   // ~one jaw drop per few letters (syllables)
                const per = dur / moves;
                for (let i = 0; i < moves; i++) {
                    frames.push([0.6 + Math.random() * 0.4, per * 0.6]);  // open (varied)
                    frames.push([0.1, per * 0.4]);                        // near-closed between syllables
                }
                // Gap after the word; longer at punctuation = a real pause.
                const last = w.slice(-1);
                let gap = 0.06;
                if (/[,;:)\\]]/.test(last)) gap = 0.22;
                else if (/[.!?\\u2026]/.test(last)) gap = 0.40;
                frames.push([0.0, gap * k]);                              // mouth shut during the gap
            }
            return frames;
        }

        // Chrome silently kills a single long utterance ~15s in — the "Blue
        // abruptly stops talking mid-reply" bug. Speak the reply as
        // sentence-sized chunks queued on speechSynthesis instead: the queue
        // survives long replies, and cancel() (barge-in, Escape, the toggle)
        // still clears the whole thing at once. The resume() keepalive
        // revives the engine when it pauses itself anyway — a second Chrome
        // quirk with some voices.
        let _speakKeepAlive = null;
        function _speakKeepAliveStart() {
            if (_speakKeepAlive) return;
            _speakKeepAlive = setInterval(function () {
                const s = window.speechSynthesis;
                if (!s.speaking && !s.pending) { clearInterval(_speakKeepAlive); _speakKeepAlive = null; return; }
                if (s.paused) { try { s.resume(); } catch (e) {} }
            }, 4000);
        }
        function speechChunks(msg) {
            const sentences = msg.match(/[^.!?…]+[.!?…]*\\s*/g) || [msg];
            const out = [];
            let cur = '';
            for (let i = 0; i < sentences.length; i++) {
                if (cur && (cur.length + sentences[i].length) > 220) { out.push(cur); cur = ''; }
                cur += sentences[i];
            }
            if (cur.trim()) out.push(cur);
            return out.length ? out : [msg];
        }

        function speak(text) {
            if (!speakOn || !('speechSynthesis' in window)) return;
            const msg = cleanForSpeech(text);
            if (!msg) return;
            const lang = langForSpeech(msg);
            const bcp = { en: 'en-US', fr: 'fr-FR', ru: 'ru-RU', el: 'el-GR', da: 'da-DK' }[lang] || 'en-US';
            try {
                window.speechSynthesis.cancel();
                // Use Vilda's chosen voice when it speaks the reply's language;
                // otherwise fall back to the automatic per-language pick.
                let v = chosenVoice();
                if (!v || (v.lang || '').toLowerCase().indexOf(lang) !== 0) v = pickVoice(lang);
                const rate = (isVilda ? 0.95 : 1.0) * ((ROBOT && ROBOT.voiceRate) || 1.0);
                // Make Blue "talk" while he reads aloud. On Vilda's iPad this
                // moves the ON-SCREEN face's mouth (the physical robot must stay
                // still for her); on Alex's devices the on-screen face doesn't
                // exist, so it just flaps the real robot's lips as before. The
                // lip-seq is a text-derived mouth schedule for the WHOLE reply
                // (jaw moves on words, closes on gaps), fired once on the first
                // chunk's start; fire-and-forget — a no-op if no head.
                const _lipFrames = (!isVilda) ? buildLipFrames(msg, rate) : null;
                let _started = false;
                const _onFirstStart = function () {
                    if (_started) return;
                    _started = true;
                    setFaceState('talking');
                    bargeInRecogStart();   // listen for "stop" the whole time he talks
                    if (!isVilda && !localHeadLip(ROBOT.head, _lipFrames)) {
                        try { fetch('/head/' + ROBOT.head + '/lip-seq', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ frames: _lipFrames }) }); } catch (e) {}
                    }
                };
                const _spokenDone = function () {
                    // Fires per chunk: only finish when the whole queued reply
                    // is done (or was cancelled) — not between chunks.
                    if (window.speechSynthesis.speaking || window.speechSynthesis.pending) return;
                    bargeInRecogStop();
                    setFaceState('');
                    if (!isVilda && !localHeadLipStop(ROBOT.head)) {
                        try { fetch('/head/' + ROBOT.head + '/lip', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"on":false}' }); } catch (e) {}
                    }
                };
                const parts = speechChunks(msg);
                for (let i = 0; i < parts.length; i++) {
                    const u = new SpeechSynthesisUtterance(parts[i]);
                    if (v) u.voice = v;
                    u.lang = bcp;
                    u.rate = rate;
                    u.pitch = (ROBOT && ROBOT.voicePitch) || 1.0;
                    u.onstart = _onFirstStart;
                    u.onend = _spokenDone;
                    u.onerror = _spokenDone;
                    window.speechSynthesis.speak(u);
                }
                _speakKeepAliveStart();
            } catch (e) { /* ignore */ }
        }

        // If the user navigates away mid-speech, the lip thread on the server
        // would keep flapping until the next speech start. Make sure to stop.
        window.addEventListener('pagehide', function () {
            if (isVilda) return;   // her iPad never drives the head; nothing to stop
            if (localHeadLipStop(ROBOT.head)) return;   // a head on THIS device — stop it locally
            try { navigator.sendBeacon && navigator.sendBeacon('/head/' + ROBOT.head + '/lip', new Blob(['{"on":false}'], { type: 'application/json' })); } catch (e) {}
        });

        if ('speechSynthesis' in window) {
            try { window.speechSynthesis.onvoiceschanged = function () { window.speechSynthesis.getVoices(); }; } catch (e) {}
        }

        function setSpeakOn(on) {
            speakOn = on;
            speakBtn.classList.toggle('active', on);
            speakBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
            if (!on && 'speechSynthesis' in window) window.speechSynthesis.cancel();
        }
        speakBtn.addEventListener('click', () => { primeAudio(); setSpeakOn(!speakOn); });
        setSpeakOn(speakOn);

        // Local USB-C head (Web Serial), same engine as duet: drive a head plugged
        // into THIS device straight from the page. Only on a capable non-PC device
        // (Chrome + https) for Alex; the PC keeps using the server, and the kid's
        // iPad / Safari stay voice-only. The shared /js/ohbot-heads.js provides
        // WEBSERIAL_OK / DRIVES_HEADS / LOCAL_DRIVERS / connectHead / disconnectHead.
        (function () {
            const btn = document.getElementById('connHeadBtn');
            if (!btn || !(WEBSERIAL_OK && !DRIVES_HEADS && !isVilda)) return;
            btn.style.display = '';
            function paint() {
                const on = !!LOCAL_DRIVERS[ROBOT.head];
                btn.classList.toggle('active', on);
                btn.setAttribute('aria-pressed', on ? 'true' : 'false');
                btn.title = on ? 'Head connected on this device — tap to release'
                               : "Drive the head from this device's USB-C port";
            }
            window.onLocalHeadsChanged = paint;
            btn.addEventListener('click', function () {
                primeAudio();
                if (LOCAL_DRIVERS[ROBOT.head]) disconnectHead(ROBOT.head); else connectHead(ROBOT.head);
            });
            paint();
        })();

        // ---- Research mode: search the web before answering ----
        // Opt-in, saved per device per robot: while the magnifier is lit,
        // every message first runs a live web search server-side and the
        // findings ride along as context for the reply.
        const researchBtn = document.getElementById('researchBtn');
        let researchOn = false;
        try { researchOn = localStorage.getItem('blueResearch_' + ROBOT.id) === '1'; } catch (e) {}
        if (!researchBtn) researchOn = false;   // kid pages have no toggle and no research
        function setResearchOn(on) {
            researchOn = on;
            if (!researchBtn) return;
            researchBtn.classList.toggle('active', on);
            researchBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
            try { localStorage.setItem('blueResearch_' + ROBOT.id, on ? '1' : '0'); } catch (e) {}
        }
        if (researchBtn) {
            researchBtn.addEventListener('click', () => setResearchOn(!researchOn));
            setResearchOn(researchOn);
        }

        // ---- Wikipedia consult: read the encyclopedia before answering ----
        // Opt-in, saved per device per robot: while the book is lit, every
        // message first pulls the best-matching Wikipedia article server-side
        // and its summary rides along as context. Independent of web research.
        const wikiBtn = document.getElementById('wikiBtn');
        let wikiOn = false;
        try { wikiOn = localStorage.getItem('blueWiki_' + ROBOT.id) === '1'; } catch (e) {}
        if (!wikiBtn) wikiOn = false;   // kid pages have no toggle
        function setWikiOn(on) {
            wikiOn = on;
            if (!wikiBtn) return;
            wikiBtn.classList.toggle('active', on);
            wikiBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
            try { localStorage.setItem('blueWiki_' + ROBOT.id, on ? '1' : '0'); } catch (e) {}
        }
        if (wikiBtn) {
            wikiBtn.addEventListener('click', () => setWikiOn(!wikiOn));
            setWikiOn(wikiOn);
        }

        // ---- Context & focus: where we are + which library docs to lean on ----
        // The picker scopes Blue's specialized knowledge for the conversation;
        // an empty selection = his whole library (unchanged behaviour). Saved
        // per device per robot, like the other toggles. The location override
        // lives server-side (data/place.json) so every device agrees on it.
        const contextBtn = document.getElementById('contextBtn');
        const contextPanel = document.getElementById('contextPanel');
        let FOCUS = { docs: [], folders: [] };
        try { FOCUS = JSON.parse(localStorage.getItem('blueFocus_' + ROBOT.id)) || FOCUS; } catch (e) {}
        if (!FOCUS || typeof FOCUS !== 'object') FOCUS = { docs: [], folders: [] };
        FOCUS.docs = Array.isArray(FOCUS.docs) ? FOCUS.docs : [];
        FOCUS.folders = Array.isArray(FOCUS.folders) ? FOCUS.folders : [];

        function focusCount() { return FOCUS.docs.length + FOCUS.folders.length; }
        function paintContextBtn() {
            if (!contextBtn) return;
            const n = focusCount();
            contextBtn.classList.toggle('active', n > 0);
            contextBtn.setAttribute('aria-pressed', n > 0 ? 'true' : 'false');
            contextBtn.title = n > 0 ? (n + ' library item(s) focused — tap to change')
                                     : 'Focus ' + ROBOT.name + ' on specific library documents';
        }
        function updateCtxCount() {
            const el = document.getElementById('ctxCount');
            if (!el) return;
            if (focusCount() === 0) { el.textContent = 'No documents focused'; return; }
            const parts = [];
            if (FOCUS.docs.length) parts.push(FOCUS.docs.length + ' doc' + (FOCUS.docs.length > 1 ? 's' : ''));
            if (FOCUS.folders.length) parts.push(FOCUS.folders.length + ' folder' + (FOCUS.folders.length > 1 ? 's' : ''));
            el.textContent = parts.join(', ') + ' focused';
        }
        function saveFocus() {
            try { localStorage.setItem('blueFocus_' + ROBOT.id, JSON.stringify(FOCUS)); } catch (e) {}
            paintContextBtn();
            updateCtxCount();
        }
        function renderCtxList(data) {
            const list = document.getElementById('ctxList');
            if (!list) return;
            const docs = (data && data.documents) || [];
            if (!docs.length) {
                list.innerHTML = '<div class="voice-empty">Your library is empty. Add documents on the Library page first.</div>';
                updateCtxCount();
                return;
            }
            const groups = {};
            docs.forEach(function (d) {
                const f = d.folder || '';
                if (!groups[f]) groups[f] = [];
                groups[f].push(d);
            });
            let html = '';
            Object.keys(groups).sort().forEach(function (f) {
                if (f !== '') {
                    const fchecked = FOCUS.folders.indexOf(f) >= 0 ? 'checked' : '';
                    html += '<label class="ctx-folder"><input type="checkbox" class="ctx-fchk" data-folder="'
                          + esc(f) + '" ' + fchecked + '> ' + esc(f) + '</label>';
                } else {
                    html += '<div class="ctx-folder">Library root</div>';
                }
                groups[f].forEach(function (d) {
                    const checked = FOCUS.docs.indexOf(d.filename) >= 0;
                    html += '<label class="ctx-item' + (checked ? ' sel' : '') + '">'
                          + '<input type="checkbox" class="ctx-dchk" data-doc="' + esc(d.filename) + '" '
                          + (checked ? 'checked' : '') + '>'
                          + '<span class="ci-main"><span class="ci-name">' + esc(d.filename) + '</span>'
                          + (d.preview ? ('<span class="ci-prev">' + esc(d.preview) + '</span>') : '')
                          + '</span></label>';
                });
            });
            list.innerHTML = html;
            list.querySelectorAll('.ctx-dchk').forEach(function (cb) {
                cb.addEventListener('change', function () {
                    const name = cb.getAttribute('data-doc');
                    const i = FOCUS.docs.indexOf(name);
                    if (cb.checked && i < 0) FOCUS.docs.push(name);
                    else if (!cb.checked && i >= 0) FOCUS.docs.splice(i, 1);
                    const item = cb.closest('.ctx-item');
                    if (item) item.classList.toggle('sel', cb.checked);
                    saveFocus();
                });
            });
            list.querySelectorAll('.ctx-fchk').forEach(function (cb) {
                cb.addEventListener('change', function () {
                    const f = cb.getAttribute('data-folder');
                    const i = FOCUS.folders.indexOf(f);
                    if (cb.checked && i < 0) FOCUS.folders.push(f);
                    else if (!cb.checked && i >= 0) FOCUS.folders.splice(i, 1);
                    saveFocus();
                });
            });
            updateCtxCount();
        }
        function loadPlace() {
            fetch('/place').then(function (r) { return r.json(); }).then(function (p) {
                const now = document.getElementById('placeNow');
                const inp = document.getElementById('placeInput');
                if (!now) return;
                if (p.current) {
                    now.textContent = 'Right now: ' + p.current + '. Tap "Back home" to reset.';
                    if (inp) inp.value = p.current;
                } else {
                    now.textContent = 'Right now: at ' + (p.home || 'home') + (p.city ? (' in ' + p.city) : '') + '.';
                    if (inp) inp.value = '';
                }
            }).catch(function () {});
        }
        function setPlace(val) {
            fetch('/place', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({ current: val }) })
                .then(function (r) { return r.json(); }).then(loadPlace).catch(function () {});
        }
        function loadCtxLibrary() {
            fetch('/api/library/list').then(function (r) { return r.json(); })
                .then(renderCtxList).catch(function () {
                    const list = document.getElementById('ctxList');
                    if (list) list.innerHTML = '<div class="voice-empty">Could not load your library.</div>';
                });
        }
        if (contextBtn && contextPanel) {
            contextBtn.addEventListener('click', function () {
                primeAudio();
                loadPlace();
                loadCtxLibrary();
                updateCtxCount();
                contextPanel.style.display = 'flex';
            });
            document.getElementById('contextClose').addEventListener('click', function () { contextPanel.style.display = 'none'; });
            contextPanel.addEventListener('click', function (e) { if (e.target === contextPanel) contextPanel.style.display = 'none'; });
            const pinp = document.getElementById('placeInput');
            const pset = document.getElementById('placeSet');
            const phome = document.getElementById('placeHome');
            if (pset) pset.addEventListener('click', function () { setPlace(pinp ? pinp.value.trim() : ''); });
            if (pinp) pinp.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); setPlace(pinp.value.trim()); } });
            if (phome) phome.addEventListener('click', function () { setPlace(''); });
            const cclear = document.getElementById('ctxClear');
            if (cclear) cclear.addEventListener('click', function () { FOCUS = { docs: [], folders: [] }; saveFocus(); loadCtxLibrary(); });
        }
        paintContextBtn();

        // ---- Language setting: which language Alex speaks AND Blue replies in ----
        // 'auto' = Whisper detects per clip (constrained server-side to the
        // family's five languages). A fixed code rides along with every /stt
        // clip — skipping detection entirely, which is what actually makes
        // short multilingual utterances reliable — and with every chat request
        // so Blue answers in the same language. Saved per device, per robot.
        const LANGS = [
            ['auto', 'Auto'], ['en', 'English'], ['fr', 'Fran\\u00e7ais'],
            ['ru', '\\u0420\\u0443\\u0441\\u0441\\u043a\\u0438\\u0439'],
            ['el', '\\u0395\\u03bb\\u03bb\\u03b7\\u03bd\\u03b9\\u03ba\\u03ac'],
            ['da', 'Dansk']
        ];
        let LANG_MODE = 'auto';
        try { LANG_MODE = localStorage.getItem('blueLang_' + ROBOT.id) || 'auto'; } catch (e) {}
        if (!LANGS.some(function (l) { return l[0] === LANG_MODE; })) LANG_MODE = 'auto';

        function setLangMode(code) {
            LANG_MODE = code;
            try { localStorage.setItem('blueLang_' + ROBOT.id, code); } catch (e) {}
            buildLangRow();
        }

        function buildLangRow() {
            const row = document.getElementById('langRow');
            if (!row) return;
            row.innerHTML = '';
            LANGS.forEach(function (l) {
                const b = document.createElement('button');
                b.className = 'lang-chip' + (l[0] === LANG_MODE ? ' sel' : '');
                b.textContent = l[1];
                b.addEventListener('click', function () { primeAudio(); setLangMode(l[0]); });
                row.appendChild(b);
            });
        }

        // The language Blue should SPEAK a reply in: the explicit setting,
        // unless the reply's own script contradicts it — Cyrillic or Greek
        // text never lies, whereas en/fr/da are script-ambiguous, so for
        // those the setting beats the word-list guess in detectLang().
        function langForSpeech(msg) {
            const det = detectLang(msg);
            if (LANG_MODE === 'auto') return det;
            if (det === 'ru' || det === 'el') return det;
            if (LANG_MODE === 'ru' || LANG_MODE === 'el') return det;
            return LANG_MODE;
        }

        // ---- Voice picker: tap a voice to hear it, tap to keep it (saved per device) ----
        const voiceBtn = document.getElementById('voiceBtn');
        const voicePanel = document.getElementById('voicePanel');
        const voiceClose = document.getElementById('voiceClose');
        const voiceList = document.getElementById('voiceList');
        const VOICE_SAMPLES = { en: "Hi, I'm Blue!", fr: 'Bonjour, je suis Blue\\u00a0!', ru: '\\u041f\\u0440\\u0438\\u0432\\u0435\\u0442, \\u044f \\u0411\\u043b\\u044e!', el: '\\u0393\\u0435\\u03b9\\u03b1, \\u03b5\\u03af\\u03bc\\u03b1\\u03b9 \\u03bf \\u039c\\u03c0\\u03bb\\u03b5!', da: 'Hej, jeg er Blue!' };

        function voiceLangCode(v) {
            const l = (v.lang || '').toLowerCase();
            if (l.indexOf('fr') === 0) return 'fr';
            if (l.indexOf('ru') === 0) return 'ru';
            if (l.indexOf('el') === 0) return 'el';
            if (l.indexOf('da') === 0) return 'da';
            if (l.indexOf('en') === 0) return 'en';
            return null;
        }

        function buildVoiceList() {
            const voices = (window.speechSynthesis && window.speechSynthesis.getVoices()) || [];
            const supported = voices.filter(voiceLangCode);
            let chosen = '';
            try { chosen = localStorage.getItem('blueVoiceName_' + ROBOT.id) || (ROBOT.id === 'blue' ? (localStorage.getItem('blueVoiceName') || '') : ''); } catch (e) {}
            voiceList.innerHTML = '';
            if (!supported.length) {
                voiceList.innerHTML = '<div class="voice-empty">No voices are installed on this device yet.</div>';
                return;
            }
            supported.forEach(function (v) {
                const row = document.createElement('button');
                row.className = 'voice-row' + (v.name === chosen ? ' sel' : '');
                row.innerHTML = '<span class="vn">' + esc(v.name) + '</span><span class="vl">' + esc(v.lang) + '</span>';
                row.addEventListener('click', function () {
                    primeAudio();
                    try { localStorage.setItem('blueVoiceName_' + ROBOT.id, v.name); } catch (e) {}
                    try {
                        window.speechSynthesis.cancel();
                        const code = voiceLangCode(v) || 'en';
                        const u = new SpeechSynthesisUtterance(VOICE_SAMPLES[code] || VOICE_SAMPLES.en);
                        u.voice = v; u.lang = v.lang || 'en-US';
                        window.speechSynthesis.speak(u);
                    } catch (e) {}
                    buildVoiceList();
                });
                voiceList.appendChild(row);
            });
        }

        if (voiceBtn) {
            voiceBtn.addEventListener('click', function () { primeAudio(); buildLangRow(); buildVoiceList(); voicePanel.style.display = 'flex'; });
            voiceClose.addEventListener('click', function () { voicePanel.style.display = 'none'; });
            voicePanel.addEventListener('click', function (e) { if (e.target === voicePanel) voicePanel.style.display = 'none'; });
        }

        // The iPad Mini (iOS 12) has no MediaRecorder, so we capture raw audio
        // with the Web Audio API (works back to iOS 12) and encode a WAV here,
        // then POST it to /stt for Blue to transcribe on the PC.
        // Set the mic up ONCE and keep it running. iOS Safari (iOS 12) both caps
        // how many AudioContexts a page may create AND yields SILENT audio when a
        // MediaStreamSource is re-attached to a context — which is why tearing
        // down and rebuilding per recording produced 6s of pure silence. So we
        // build the context + mic + nodes a single time, leave them connected,
        // and just gate sample collection with the `recording` flag.
        let listening = false, recording = false, audioReady = false;
        let audioCtx = null, micStream = null, srcNode = null, procNode = null;
        let pcmChunks = [], recSampleRate = 16000, autoStopTimer = null;
        const hintEl = document.querySelector('.hint');
        const originalHint = hintEl ? hintEl.textContent : '';
        const defaultHint = isVilda ? 'Tap the microphone and talk to Blue.' : originalHint;
        function setHint(t) { if (hintEl) hintEl.textContent = t; }
        setHint(defaultHint);

        // Returns true once the mic graph is live; 'denied' / 'unsupported' otherwise.
        // CRITICAL on iOS: both audioCtx.resume() and getUserMedia() must be
        // *initiated* synchronously inside the tap gesture (before any await),
        // or iOS leaves the context suspended and nothing is ever captured.
        async function ensureAudio() {
            const AC = window.AudioContext || window.webkitAudioContext;
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !AC) return 'unsupported';
            try { if (!audioCtx) audioCtx = new AC(); } catch (e) { return 'unsupported'; }
            // Kick both off NOW, while still in the gesture; await afterwards.
            const resumeP = (audioCtx.state !== 'running') ? audioCtx.resume() : null;
            // echoCancellation matters for barge-in ("stop" while Blue talks):
            // it suppresses Blue's own voice coming back through the mic so we
            // don't hear (or transcribe) him saying his own words.
            const _audioConstraints = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
            const mediaP = audioReady ? null : navigator.mediaDevices.getUserMedia({ audio: _audioConstraints }).catch(function () {
                return navigator.mediaDevices.getUserMedia({ audio: true });  // fallback if constraints unsupported
            });
            if (resumeP) { try { await resumeP; } catch (e) {} }
            if (audioReady && audioCtx.state !== 'closed') return true;
            let stream;
            try { stream = await mediaP; } catch (e) { return 'denied'; }
            micStream = stream;
            recSampleRate = audioCtx.sampleRate || 44100;
            srcNode = audioCtx.createMediaStreamSource(micStream);
            procNode = audioCtx.createScriptProcessor(4096, 1, 1);
            procNode.onaudioprocess = audioProcessHandler;
            const mute = audioCtx.createGain();
            mute.gain.value = 0;
            srcNode.connect(procNode);
            procNode.connect(mute);
            mute.connect(audioCtx.destination);
            // iOS may garbage-collect the source/stream and then feed silence;
            // pin everything to a global so it can't be collected.
            window.__blueKeep = [audioCtx, srcNode, procNode, mute, micStream];
            try {
                const tr0 = micStream.getAudioTracks ? micStream.getAudioTracks()[0] : null;
                if (tr0) tr0.enabled = true;
            } catch (e) {}
            audioReady = true;
            return true;
        }

        function encodeWav(chunks, sampleRate) {
            let len = 0;
            for (let i = 0; i < chunks.length; i++) len += chunks[i].length;
            const buf = new ArrayBuffer(44 + len * 2);
            const view = new DataView(buf);
            function ws(off, s) { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); }
            ws(0, 'RIFF'); view.setUint32(4, 36 + len * 2, true); ws(8, 'WAVE');
            ws(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
            view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true);
            view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
            ws(36, 'data'); view.setUint32(40, len * 2, true);
            let off = 44;
            for (let i = 0; i < chunks.length; i++) {
                const c = chunks[i];
                for (let j = 0; j < c.length; j++) {
                    let v = c[j]; if (v > 1) v = 1; else if (v < -1) v = -1;
                    view.setInt16(off, v < 0 ? v * 0x8000 : v * 0x7FFF, true); off += 2;
                }
            }
            return new Blob([view], { type: 'audio/wav' });
        }

        function stopListening() {
            if (autoStopTimer) { clearTimeout(autoStopTimer); autoStopTimer = null; }
            if (!recording) return;
            recording = false;
            listening = false;
            micBtn.classList.remove('listening');
            const chunks = pcmChunks;
            pcmChunks = [];
            transcribePcm(chunks, recSampleRate);
        }

        async function startListening() {
            primeAudio();
            if ('speechSynthesis' in window) window.speechSynthesis.cancel();
            if (recording) { stopListening(); return; }
            const ok = await ensureAudio();
            if (ok === 'denied') {
                addBubble('blue', 'I need permission to use the microphone. Tap the mic again and choose Allow.');
                return;
            }
            if (ok !== true) {
                if (!window.isSecureContext) {
                    addBubble('blue', 'Please open me at my secure address first: https://ai-workstation.tail211c96.ts.net/chat \\u2014 then the microphone will work.');
                } else {
                    addBubble('blue', 'This browser will not let me use the microphone.');
                }
                return;
            }
            if (audioCtx.state !== 'running') { try { await audioCtx.resume(); } catch (e) {} }
            pcmChunks = [];
            recording = true;
            listening = true;
            micBtn.classList.add('listening');
            setFaceState('listening');
            setHint('Listening\\u2026 tap the microphone again when you are done.');
            autoStopTimer = setTimeout(stopListening, 15000);
        }

        async function transcribePcm(chunks, sampleRate) {
            let total = 0;
            for (let i = 0; i < chunks.length; i++) total += chunks[i].length;
            if (!total) {
                setHint(defaultHint);
                addBubble('blue', 'I did not hear anything that time \\u2014 tap the mic, wait a second, then talk.');
                faceCuriousBriefly();
                return;
            }
            const blob = encodeWav(chunks, sampleRate);
            const fd = new FormData();
            fd.append('audio', blob, 'speech.wav');
            if (LANG_MODE !== 'auto') fd.append('language', LANG_MODE);
            micBtn.disabled = true;
            setHint('Figuring out what you said\\u2026');
            setFaceState('thinking');
            try {
                const res = await fetch('/stt', { method: 'POST', body: fd });
                const data = await res.json().catch(() => null);
                const said = (data && data.text || '').trim();
                if (said) { inputEl.value = said; pendingVoice = true; send(); }
                else { addBubble('blue', 'I did not catch that \\u2014 tap the mic and try again.'); faceCuriousBriefly(); }
            } catch (e) {
                addBubble('blue', 'I could not hear that just now. Tap the mic and try again.');
                faceCuriousBriefly();
            } finally {
                micBtn.disabled = false;
                setHint(defaultHint);
            }
        }

        micBtn.addEventListener('click', startListening);

        // ======================================================================
        // ---- Robot camera live preview: see through the camera BEFORE a
        // capture. Steer the head, set the zoom — then "what do you see?"
        // photographs exactly the previewed view (capture reuses the preview's
        // camera while the panel is open).
        const camBtn = document.getElementById('camBtn');
        const camPanel = document.getElementById('camPanel');
        if (camBtn && camPanel) {
            const camImg = document.getElementById('camStream');
            const camVal = document.getElementById('camZoomVal');
            let camZoom = 1.0;
            function camShowZoom() { camVal.textContent = (Math.round(camZoom * 10) / 10) + '\\u00d7'; }
            function camOpen() {
                camPanel.style.display = 'flex';
                camImg.src = '/camera/stream?ts=' + Date.now();
                camBtn.classList.add('active'); camBtn.setAttribute('aria-pressed', 'true');
            }
            function camShut() {
                camPanel.style.display = 'none';
                camImg.removeAttribute('src');   // drops the MJPEG connection
                camBtn.classList.remove('active'); camBtn.setAttribute('aria-pressed', 'false');
            }
            function camPtz(body) {
                fetch('/camera/ptz', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
                    .then(r => r.json())
                    .then(d => { if (d && typeof d.zoom === 'number') { camZoom = d.zoom; camShowZoom(); } })
                    .catch(() => {});
            }
            camBtn.addEventListener('click', () => { (camPanel.style.display === 'none') ? camOpen() : camShut(); });
            document.getElementById('camClose').addEventListener('click', camShut);
            camPanel.addEventListener('click', (e) => { if (e.target === camPanel) camShut(); });
            camPanel.querySelectorAll('[data-look]').forEach(b => b.addEventListener('click', () => camPtz({ look: b.getAttribute('data-look') })));
            document.getElementById('camZoomIn').addEventListener('click', () => camPtz({ zoom: Math.min(4, camZoom + 0.5) }));
            document.getElementById('camZoomOut').addEventListener('click', () => camPtz({ zoom: Math.max(1, camZoom - 0.5) }));
            camShowZoom();
        }

        // ======================================================================
        // Hands-free mode: continuous listening, wake on "Blue", auto-stop on
        // silence. A second option alongside tap-to-talk; toggled by hfBtn.
        // ======================================================================
        let handsFree = false;
        let hfVoicing = false;          // currently capturing an utterance
        let hfSilence = 0;              // consecutive silent chunks during voicing
        let hfPreroll = [];             // last few silent chunks, prepended on voice start
        // Barge-in ("stop" while Blue is speaking) capture state.
        let biActive = false, biChunks = [], biVoice = 0, biSilence = 0, biBusy = false;
        let biPreroll = [];                // rolling pre-roll so the "st-" onset isn't clipped
        // Sensitive on purpose: starting a capture does NOT stop Blue — only a
        // transcript that matches "stop" does. So we capture eagerly at quiet
        // speaking volume; echo cancellation keeps Blue's own voice out.
        const BI_THRESHOLD_FACTOR = 1.0;   // right at the normal voice threshold
        const BI_THRESHOLD_MIN = 0.010;    // very low floor — a soft "stop" should land
        const BI_VOICE_START = 1;          // react on the first loud chunk
        const BI_PREROLL_MAX = 4;          // ~0.37s kept before onset (captures the "st")
        const BI_SILENCE_END = 3;          // ~0.28s of quiet ends the barge-in clip
        const BI_MAX_CHUNKS = 9;           // ~0.84s cap — short clips = fast verdicts;
                                           // Blue's echo rarely lets the mic go quiet
        // ONLY "stop" interrupts (per request). Lenient: matches "stop" anywhere
        // plus the closest mis-hearings Whisper produces (stahp/stawp/staap/stop).
        const BI_STOP = /\\bst[aou]+w?h?p\\b|\\bstop\\b/i;
        let biPending = null;              // clip captured while another was at /stt
        let hfProcessing = false;       // /stt in flight or send() running
        let hfWakeArmed = false;        // user said "Blue" alone; next utterance is the message
        let hfArmedTimer = null;
        let hfNoiseFloor = 0.005;       // running estimate of ambient RMS (adapts to room)
        let hfVoiceRamp = 0;            // consecutive above-threshold chunks before we commit
        let hfVoicyCount = 0;           // voiced chunks in the current utterance

        // VAD tuning. Noise rejection is layered: an adaptive floor (so quiet
        // rooms stay sensitive and loud rooms get stricter), a ramp-up so a
        // single pop can't open a recording, and a minimum voiced duration so
        // very short noises get discarded before they ever reach Whisper.
        const HF_NOISE_ALPHA = 0.05;       // EMA smoothing on the ambient floor
        // VAD thresholds derived from the hands-free sensitivity slider on /head
        // (0 = strict, 10 = very sensitive). Initial value comes from the server.
        let HF_THRESHOLD_FACTOR = 2.4;
        let HF_THRESHOLD_MIN = 0.018;
        let HF_VOICE_RAMP = 2;
        let HF_MIN_VOICE_CHUNKS = 3;
        function applyHfSensitivity(s) {
            s = Math.max(0, Math.min(10, Number(s)));
            if (isNaN(s)) s = 5;
            HF_THRESHOLD_FACTOR = 4.0 - (s / 10) * 2.5;        // 4.0 (strict) → 1.5 (loose)
            HF_THRESHOLD_MIN    = 0.040 - (s / 10) * 0.032;    // 0.040 → 0.008
            HF_VOICE_RAMP        = s <= 3 ? 3 : (s <= 7 ? 2 : 1);
            HF_MIN_VOICE_CHUNKS  = s <= 3 ? 5 : (s <= 7 ? 3 : 2);
        }
        applyHfSensitivity({{ hf_sens|default(5) }});
        const HF_SILENCE_CHUNKS = 9;       // ~0.85s of silence ends the utterance (snappier)
        const HF_PREROLL_MAX = 4;          // ~0.37s of pre-roll keeps the first phoneme
        const HF_MAX_CHUNKS = 250;         // ~23s cap per utterance
        const HF_ARMED_MS = 15000;         // bare-"Blue" wait window before the message
        // Whisper hallucinates a small set of stock phrases when fed near-silence
        // or non-speech noise. Drop these before they trigger anything.
        const HF_HALLUC = /^\\s*(?:(?:thanks?(?:\\s+for\\s+watching)?|thank\\s+you|you|bye|\\.|subtitles?\\s+by[^.]*|amara\\.org|MBC\\b[^.]*|copyright[^.]*)[!\\.\\?\\s]*)+$/i;

        // Two hands-free modes (toggle on the page, remembered per device):
        //   'wake'         — must start with "Blue"; noise-gated, always-on safe.
        //   'conversation' — no wake word; every utterance goes to Blue.
        let hfMode = 'wake';
        try { hfMode = localStorage.getItem('blueHfMode') || 'wake'; } catch (e) {}

        // Fillers Whisper may stick before the name; allowed to precede the wake.
        const HF_FILLERS = ['hey','hi','hello','ok','okay','um','uh','so','well'];
        // Accepted spellings of the wake word (Whisper is inconsistent on a short
        // leading proper noun, even with hotword biasing). The Cyrillic/Greek
        // entries matter when the language setting fixes Russian/Greek: Whisper
        // then writes the name natively ("\\u0411\\u043b\\u044e," / "\\u039c\\u03c0\\u03bb\\u03b5") and the latin-only
        // strip below would otherwise erase it entirely.
        const HF_WAKE_WORDS = ['blue','bleu','blu','blew','bloo','blues','bews',
            '\\u0431\\u043b\\u044e','\\u0431\\u043b\\u0443','\\u0431\\u043b\\u044c\\u044e','\\u0431\\u043b\\u0435',
            '\\u03bc\\u03c0\\u03bb\\u03b5','\\u03bc\\u03c0\\u03bb\\u03bf\\u03c5'];
        function isWakeWord(w) {
            // Unicode-aware pass first: keep latin, Cyrillic and Greek letters,
            // drop punctuation — so "\\u0411\\u043b\\u044e," matches its list entry.
            const wu = w.toLowerCase().replace(/[^a-z\\u00e0-\\u00ff\\u0370-\\u03ff\\u0400-\\u04ff]/g, '');
            if (wu && HF_WAKE_WORDS.indexOf(wu) >= 0) return true;
            w = w.toLowerCase().replace(/[^a-z]/g, '');
            if (!w) return false;
            if (HF_WAKE_WORDS.indexOf(w) >= 0) return true;
            // edit-distance ≤1 from "blue" catches Boo/Blu/Blhe/etc. without a lib
            if (Math.abs(w.length - 4) > 1) return false;
            let i = 0, j = 0, edits = 0; const t = 'blue';
            while (i < w.length && j < t.length) {
                if (w[i] === t[j]) { i++; j++; }
                else { edits++; if (edits > 1) return false;
                    if (w.length > t.length) i++; else if (w.length < t.length) j++; else { i++; j++; } }
            }
            return (edits + (w.length - i) + (t.length - j)) <= 1;
        }
        // Returns the message after the wake word, '' if wake-only, or null if no wake.
        function extractWake(said) {
            const words = said.trim().split(/\\s+/);
            for (let i = 0; i < Math.min(3, words.length); i++) {
                if (isWakeWord(words[i])) return words.slice(i + 1).join(' ').replace(/^[\\s,.\\?!:;\\-]+/, '').trim();
                // Only fillers (hi/hey/um…) may precede the wake word; strip
                // punctuation Whisper attaches ("Um," -> "um") before comparing.
                if (HF_FILLERS.indexOf(words[i].toLowerCase().replace(/[^a-z]/g, '')) < 0) break;
            }
            return null;
        }

        const hfBtn = document.getElementById('hfBtn');
        const hfStatusEl = document.getElementById('hfStatus');
        // Tapping the status pill while Blue talks silences him (works even if
        // the mic mishears — a guaranteed manual out).
        if (hfStatusEl) {
            hfStatusEl.style.cursor = 'pointer';
            hfStatusEl.addEventListener('click', function () {
                if (window.speechSynthesis && window.speechSynthesis.speaking) stopSpeaking('tap');
            });
        }

        function setHfStatus(state) {
            if (!hfStatusEl) return;
            if (!handsFree) { hfStatusEl.style.display = 'none'; hfStatusEl.className = 'hf-status'; return; }
            const waitLabel = hfMode === 'conversation' ? 'Conversation on \\u2014 just talk\\u2026' : 'Listening for "Blue"\\u2026';
            const labels = {
                waiting:  waitLabel,
                voicing:  'Listening to you\\u2026',
                thinking: 'Thinking\\u2026',
                armed:    'Yes? I\\'m listening\\u2026',
                replying: 'Speaking\\u2026 say "stop" or tap here',
            };
            hfStatusEl.style.display = 'flex';
            hfStatusEl.className = 'hf-status ' + (state || '');
            hfStatusEl.textContent = labels[state] || labels.waiting;
        }

        // Mode toggle (Conversation vs wake word). Shown only while listening.
        function setHfMode(mode) {
            hfMode = (mode === 'conversation') ? 'conversation' : 'wake';
            try { localStorage.setItem('blueHfMode', hfMode); } catch (e) {}
            const mb = document.getElementById('hfModeBtn');
            if (mb) mb.textContent = hfMode === 'conversation' ? 'Mode: conversation (no wake word)' : 'Mode: say "Blue" first';
            if (handsFree && !hfProcessing) setHfStatus('waiting');
        }

        // Single onaudioprocess callback; routes samples to tap-to-talk OR hands-free.
        function audioProcessHandler(ev) {
            const samples = ev.inputBuffer.getChannelData(0);
            if (recording) {
                pcmChunks.push(new Float32Array(samples));
                return;
            }
            if (handsFree) handsFreeOnSamples(samples);
        }

        function handsFreeOnSamples(samples) {
            // Don't kick off a second utterance while one is being processed.
            if (hfProcessing) return;
            // While Blue is talking, run the barge-in listener instead of the
            // normal capture — that's how "stop" interrupts him.
            if (window.speechSynthesis && window.speechSynthesis.speaking) {
                bargeInOnSamples(samples);
                return;
            }
            // Just finished speaking? clear any half-built barge-in capture.
            if (biActive || biChunks.length) { biActive = false; biChunks = []; biVoice = 0; biSilence = 0; biPreroll = []; }

            let sum = 0;
            for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
            const rms = Math.sqrt(sum / samples.length);

            // Adaptive threshold: stays well above ambient. We only update the
            // noise floor while we're sure we're NOT hearing the user (idle).
            const threshold = Math.max(HF_THRESHOLD_MIN, hfNoiseFloor * HF_THRESHOLD_FACTOR);
            const isVoice = rms > threshold;
            if (!isVoice && !hfVoicing) {
                hfNoiseFloor = hfNoiseFloor * (1 - HF_NOISE_ALPHA) + rms * HF_NOISE_ALPHA;
            }

            if (isVoice) {
                hfVoiceRamp = Math.min(hfVoiceRamp + 1, HF_VOICE_RAMP + 2);
                if (!hfVoicing) {
                    if (hfVoiceRamp < HF_VOICE_RAMP) {
                        // Treat the candidate chunks as pre-roll — if they really
                        // are speech, we'll keep them; if it's a transient noise,
                        // the ramp won't reach HF_VOICE_RAMP and we discard them.
                        hfPreroll.push(new Float32Array(samples));
                        if (hfPreroll.length > HF_PREROLL_MAX) hfPreroll.shift();
                        return;
                    }
                    hfVoicing = true;
                    hfSilence = 0;
                    hfVoicyCount = 0;
                    pcmChunks = hfPreroll.slice();    // commit the pre-roll
                    setHfStatus('voicing');
                }
                pcmChunks.push(new Float32Array(samples));
                hfVoicyCount++;
                hfSilence = 0;
                if (pcmChunks.length > HF_MAX_CHUNKS) hfFinalize();
            } else {
                hfVoiceRamp = Math.max(0, hfVoiceRamp - 1);
                if (hfVoicing) {
                    pcmChunks.push(new Float32Array(samples));   // small tail
                    hfSilence++;
                    if (hfSilence >= HF_SILENCE_CHUNKS) {
                        // Drop "too short" utterances silently — they're almost
                        // always noise, not real speech. Saves a Whisper call AND
                        // prevents Whisper from hallucinating a wake-word match.
                        if (hfVoicyCount < HF_MIN_VOICE_CHUNKS) {
                            hfVoicing = false;
                            hfSilence = 0;
                            hfVoicyCount = 0;
                            hfPreroll = [];
                            pcmChunks = [];
                            setHfStatus(hfWakeArmed ? 'armed' : 'waiting');
                            return;
                        }
                        hfFinalize();
                    }
                } else {
                    hfPreroll.push(new Float32Array(samples));
                    if (hfPreroll.length > HF_PREROLL_MAX) hfPreroll.shift();
                }
            }
        }

        // Barge-in: while Blue is speaking, listen for a deliberate "stop".
        // Higher threshold than normal because echo cancellation isn't perfect;
        // we only want to react to the user clearly talking over Blue.
        function bargeInOnSamples(samples) {
            // NOTE: keep capturing even while a clip is at /stt (biBusy) — the
            // old early-return made Blue DEAF during each transcription, so a
            // "stop" said while his own echo was being transcribed was lost.
            let sum = 0;
            for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
            const rms = Math.sqrt(sum / samples.length);
            const threshold = Math.max(BI_THRESHOLD_MIN, hfNoiseFloor * HF_THRESHOLD_FACTOR * BI_THRESHOLD_FACTOR);
            if (rms > threshold) {
                if (!biActive) {
                    biVoice++;
                    if (biVoice < BI_VOICE_START) return;
                    // Seed with the pre-roll so the plosive onset of "stop"
                    // (the quiet "st-" just before the loud burst) is included —
                    // without it Whisper only sees "op" and you have to yell.
                    biActive = true; biChunks = biPreroll.slice(); biSilence = 0;
                }
                biChunks.push(new Float32Array(samples));
                biSilence = 0;
                if (biChunks.length > BI_MAX_CHUNKS) bargeInFinalize();
            } else {
                biVoice = Math.max(0, biVoice - 1);
                if (biActive) {
                    biChunks.push(new Float32Array(samples));
                    biSilence++;
                    if (biSilence >= BI_SILENCE_END) bargeInFinalize();
                } else {
                    biPreroll.push(new Float32Array(samples));
                    if (biPreroll.length > BI_PREROLL_MAX) biPreroll.shift();
                }
            }
        }

        async function bargeInFinalize() {
            const chunks = biChunks;
            biActive = false; biChunks = []; biVoice = 0; biSilence = 0; biPreroll = [];
            if (chunks.length < 2) return;
            if (biBusy) { biPending = chunks; return; }   // newest clip takes the queue slot
            biBusy = true;
            try {
                let clip = chunks;
                while (clip) {
                    if (!(window.speechSynthesis && window.speechSynthesis.speaking)) break;
                    const blob = encodeWav(clip, recSampleRate);
                    const fd = new FormData(); fd.append('audio', blob, 'speech.wav');
                    fd.append('hint', 'stop');   // bias Whisper toward interrupt words
                    const res = await fetch('/stt', { method: 'POST', body: fd });
                    const data = await res.json().catch(() => null);
                    const said = ((data && data.text) || '').trim();
                    // Same length guard as the speech-api path below: a real
                    // interrupt is a word or two, while Whisper — stop-biased
                    // by the hint — regularly mis-hears fragments of Blue's
                    // OWN echoed sentence as containing "stop" and silences
                    // him mid-reply. Accept a short utterance, or one that is
                    // nothing but stop-words (genuine "stop stop stop!").
                    const _biWords = said.toLowerCase().replace(/[^a-z\\s]/g, ' ').trim().split(/\\s+/).filter(function (x) { return x; });
                    const _biHasStop = said && (BI_STOP.test(said) || said.toLowerCase().indexOf('stop') >= 0);
                    if (_biHasStop && (_biWords.length <= 4 || _biWords.every(function (x) { return /^st[aou]/.test(x); }))) {
                        stopSpeaking('whisper');
                        break;
                    }
                    clip = biPending; biPending = null;   // transcribe what arrived meanwhile
                }
            } catch (e) { /* ignore */ }
            finally { biBusy = false; biPending = null; }
        }

        // ---- Stop speaking NOW — shared by every barge-in path ----
        function stopSpeaking(source) {
            try { window.speechSynthesis.cancel(); } catch (e) {}
            if (!isVilda && !localHeadLipStop(ROBOT.head)) {
                try { fetch('/head/' + ROBOT.head + '/lip', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"on":false}' }); } catch (e) {}
            }
            setFaceState('');
            biActive = false; biChunks = []; biVoice = 0; biSilence = 0; biPreroll = []; biPending = null;
            if (handsFree) setHfStatus('waiting');
        }

        // ---- FAST barge-in: the browser's own speech recognition runs WHILE
        // Blue talks and cancels him the moment an interim transcript contains
        // "stop" (~half a second). The Whisper clip path above stays as the
        // fallback — it's the only path on browsers without SpeechRecognition
        // and when there's no internet for the recognition service.
        const _BI_SR = window.SpeechRecognition || window.webkitSpeechRecognition || null;
        let biRecog = null, biRecogWanted = false;
        function bargeInRecogStart() {
            biRecogWanted = true;
            if (!_BI_SR || biRecog) return;
            if (!handsFree && !audioReady) return;   // mic not in use — don't surprise-prompt
            try {
                const r = new _BI_SR();
                r.continuous = true; r.interimResults = true; r.lang = 'en-US';
                r.onresult = function (ev) {
                    if (!(window.speechSynthesis && window.speechSynthesis.speaking)) return;
                    for (let i = ev.resultIndex; i < ev.results.length; i++) {
                        const t = (ev.results[i][0] && ev.results[i][0].transcript) || '';
                        // A short utterance containing "stop": the interrupt is a
                        // word or two, while Blue's own echoed sentences run long —
                        // the length guard keeps him from silencing himself.
                        if (BI_STOP.test(t) && t.trim().split(/\\s+/).length <= 6) { stopSpeaking('speech-api'); break; }
                    }
                };
                r.onend = function () { biRecog = null; if (biRecogWanted && window.speechSynthesis.speaking) setTimeout(bargeInRecogStart, 80); };
                r.onerror = function () { /* onend follows and decides on restart */ };
                r.start(); biRecog = r;
            } catch (e) { biRecog = null; }
        }
        function bargeInRecogStop() {
            biRecogWanted = false;
            if (biRecog) { try { biRecog.stop(); } catch (e) {} biRecog = null; }
        }
        // Escape always shuts him up, mic or no mic.
        document.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape' && window.speechSynthesis && window.speechSynthesis.speaking) stopSpeaking('esc');
        });

        async function hfFinalize() {
            hfVoicing = false;
            hfSilence = 0;
            hfPreroll = [];
            const chunks = pcmChunks; pcmChunks = [];
            if (!chunks.length) {
                setHfStatus(hfWakeArmed ? 'armed' : 'waiting');
                return;
            }
            hfProcessing = true;
            setHfStatus('thinking');
            let said = '';
            try {
                const blob = encodeWav(chunks, recSampleRate);
                const fd = new FormData(); fd.append('audio', blob, 'speech.wav');
                // In wake mode, ask the server to bias Whisper toward "Blue".
                if (hfMode !== 'conversation') fd.append('wake', '1');
                if (LANG_MODE !== 'auto') fd.append('language', LANG_MODE);
                const res = await fetch('/stt', { method: 'POST', body: fd });
                const data = await res.json().catch(() => null);
                said = ((data && data.text) || '').trim();
            } catch (e) {
                hfProcessing = false;
                if (handsFree) setHfStatus(hfWakeArmed ? 'armed' : 'waiting');
                return;
            }

            // STT is done — release the listening lock immediately so the mic
            // is hot again while the LLM is composing the reply. TTS playback
            // suspends VAD on its own via window.speechSynthesis.speaking, so
            // Blue won't hear himself, but the user CAN speak again the moment
            // the spinner stops.
            hfProcessing = false;

            // Whisper hallucinates a small set of stock phrases on near-silence.
            if (!said || said.length < 3 || HF_HALLUC.test(said)) {
                if (handsFree) setHfStatus(hfWakeArmed ? 'armed' : 'waiting');
                return;
            }

            let message = '';
            if (hfMode === 'conversation') {
                // No wake word — the whole utterance is the message.
                message = said;
            } else {
                const rest = extractWake(said);   // null = no wake word heard
                if (rest === null) {
                    if (hfWakeArmed) {
                        // We heard a bare "Blue" a moment ago; take this as the message.
                        message = said;
                        hfWakeArmed = false;
                        if (hfArmedTimer) { clearTimeout(hfArmedTimer); hfArmedTimer = null; }
                    } else {
                        if (handsFree) setHfStatus('waiting');   // background talk → ignore
                        return;
                    }
                } else if (rest === '') {
                    // Just "Blue" alone — arm for the next utterance.
                    hfWakeArmed = true;
                    if (hfArmedTimer) clearTimeout(hfArmedTimer);
                    hfArmedTimer = setTimeout(function () {
                        hfWakeArmed = false;
                        if (handsFree) setHfStatus('waiting');
                    }, HF_ARMED_MS);
                    setHfStatus('armed');
                    return;
                } else {
                    message = rest;
                }
            }

            // Fire-and-forget the chat call. The mic stays hot so the user can
            // call "Blue" again the moment the LLM starts composing — TTS will
            // self-suspend the VAD while Blue is actually speaking. No await,
            // no follow-up window: every new turn starts with "Blue".
            setHfStatus('replying');
            inputEl.value = message;
            pendingVoice = true;
            send().finally(function () {
                if (handsFree) setHfStatus(hfWakeArmed ? 'armed' : 'waiting');
            });
        }

        const hfModeBtn = document.getElementById('hfModeBtn');

        async function toggleHandsFree() {
            if (handsFree) {
                handsFree = false;
                hfVoicing = false; hfSilence = 0; hfPreroll = []; hfWakeArmed = false;
                biActive = false; biChunks = []; biVoice = 0; biSilence = 0; biPreroll = [];
                if (hfArmedTimer) { clearTimeout(hfArmedTimer); hfArmedTimer = null; }
                hfBtn.classList.remove('active');
                hfBtn.setAttribute('aria-pressed', 'false');
                if (hfModeBtn) hfModeBtn.style.display = 'none';
                setHfStatus(null);
                return;
            }
            primeAudio();
            const ok = await ensureAudio();
            if (ok !== true) {
                addBubble('blue', 'I need permission to use the microphone. Tap once to allow it.');
                return;
            }
            handsFree = true;
            hfVoicing = false; hfSilence = 0; hfPreroll = []; pcmChunks = [];
            hfVoiceRamp = 0; hfVoicyCount = 0; hfNoiseFloor = 0.005;
            hfBtn.classList.add('active');
            hfBtn.setAttribute('aria-pressed', 'true');
            if (hfModeBtn) hfModeBtn.style.display = 'block';
            setHfStatus('waiting');
        }

        if (hfBtn) hfBtn.addEventListener('click', toggleHandsFree);
        if (hfModeBtn) hfModeBtn.addEventListener('click', function () {
            setHfMode(hfMode === 'conversation' ? 'wake' : 'conversation');
        });
        setHfMode(hfMode);   // initialise the button label from saved preference

        if (isVilda) {
            micBtn.classList.add('big');
            try { fetch('/stt/warmup'); } catch (e) {}
        }

        // ===== Blue's eyes: the iPad camera, on demand (kid mode only) =====
        // Off until she taps the eye. Each tap grabs ONE frame and asks Blue to
        // look, so normal chatting stays fast. Frames go only to the local vision
        // model via /chat/eyes (never the cloud). iOS-12 safe: getUserMedia over
        // HTTPS + a <canvas> snapshot (no MediaRecorder). No-op on Alex's page
        // (no #eyeBtn there).
        const eyeBtn = document.getElementById('eyeBtn');
        if (eyeBtn) {
          // IIFE wrapper: on iOS 12 Safari, function declarations inside a bare
          // `if {}` block get hoisted out of the block while `let`/`const` stay
          // block-scoped — so the handlers couldn't see eyeBusy/eyeStream/etc.
          // ("ReferenceError: Can't find variable: eyeBusy"). A function scope
          // fixes the hoisting so the closures resolve correctly.
          (function () {
            const eyePanel = document.getElementById('eyePanel');
            const eyeVid = document.getElementById('eyeVid');
            const eyeCanvas = document.getElementById('eyeCanvas');
            const eyeFlip = document.getElementById('eyeFlip');
            const eyeClose = document.getElementById('eyeClose');
            let eyeStream = null, eyeFacing = 'user', eyeBusy = false;

            function eyeStatus(s) { /* debug tracker removed; kept as a no-op */ }

            function eyeStop() {
                if (eyeStream) { try { eyeStream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {} }
                eyeStream = null;
                try { eyeVid.srcObject = null; } catch (e) {}
                eyePanel.classList.remove('on');
                eyeBtn.classList.remove('active');
                eyeBtn.setAttribute('aria-pressed', 'false');
            }

            function eyeStart() {
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                    eyeStatus('no getUserMedia (need https?)');
                    addBubble('blue', "I can't use the camera here. Make sure you opened me at my secure https web address \\u2014 the same one the microphone needs.");
                    return Promise.reject(new Error('no-getUserMedia'));
                }
                eyeStatus('requesting camera\\u2026');
                // getUserMedia must fire inside the tap gesture on iOS.
                return navigator.mediaDevices.getUserMedia({ video: { facingMode: eyeFacing }, audio: false })
                    .then(function (stream) {
                        eyeStatus('camera on');
                        eyeStream = stream;
                        eyeVid.srcObject = stream;
                        eyePanel.classList.toggle('rear', eyeFacing !== 'user');
                        eyePanel.classList.add('on');
                        eyeBtn.classList.add('active');
                        eyeBtn.setAttribute('aria-pressed', 'true');
                        try { eyeVid.play(); } catch (e) {}
                        return new Promise(function (resolve) {
                            if (eyeVid.videoWidth > 0) { resolve(); return; }
                            eyeVid.addEventListener('loadedmetadata', function () { resolve(); }, { once: true });
                            setTimeout(resolve, 1200);
                        });
                    });
            }

            function eyeCapture() {
                const w = eyeVid.videoWidth, h = eyeVid.videoHeight;
                eyeStatus('capturing ' + w + 'x' + h);
                if (!w || !h) return null;
                const scale = Math.min(1, 640 / w);
                eyeCanvas.width = Math.round(w * scale);
                eyeCanvas.height = Math.round(h * scale);
                eyeCanvas.getContext('2d').drawImage(eyeVid, 0, 0, eyeCanvas.width, eyeCanvas.height);
                return eyeCanvas.toDataURL('image/jpeg', 0.7);
            }

            function dataUrlToBlob(durl) {
                const bin = atob(durl.split(',')[1]);
                const arr = new Uint8Array(bin.length);
                for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
                return new Blob([arr], { type: 'image/jpeg' });
            }

            function eyeUpload(durl) {
                eyeStatus('uploading frame\\u2026');
                const fd = new FormData();
                fd.append('frame', dataUrlToBlob(durl), 'eyes.jpg');
                return fetch('/chat/eyes', { method: 'POST', headers: { 'X-Blue-Device': blueDeviceTag() }, body: fd })
                    .then(function (res) {
                        if (!res || !res.ok) { throw new Error('upload HTTP ' + (res ? res.status : '?')); }
                        eyeStatus('sent to Blue');
                        return res;
                    });
            }

            // Grab+upload a frame IF the camera is open; called before every chat
            // send (via window.__blueEyeGrab) so Blue sees during the WHOLE
            // conversation, not just on the eye tap. No-op when the camera is shut.
            function grabIfOpen() {
                if (!eyeStream) return Promise.resolve(null);
                const durl = eyeCapture();
                if (!durl) return Promise.resolve(null);
                return eyeUpload(durl);
            }
            window.__blueEyeGrab = grabIfOpen;

            // Tap the eye = "Blue, look!" Starts the camera the first time, grabs
            // a frame, then sends a turn so Blue reacts to what he sees right now.
            // Turns the eye pink the INSTANT it's tapped (so a tap is always
            // visibly registered even before the camera opens), and surfaces ANY
            // camera error as a chat bubble so a silent failure can't look like
            // "nothing happened". Note: only gated on eyeBusy, not the chat's
            // `busy`, so a slow reply can't make the eye feel dead.
            function eyeLook() {
                if (eyeBusy) return;
                eyeBusy = true;
                eyeBtn.classList.add('active');
                eyeStatus('tapped');
                primeAudio();
                const go = eyeStream ? Promise.resolve() : eyeStart();
                go.then(function () {
                    // Camera is open now; send() grabs the frame via __blueEyeGrab.
                    if (!inputEl.value.trim()) inputEl.value = 'Look, Blue!';
                    send();
                }).catch(function (e) {
                    const nm = (e && e.name && e.name !== 'Error') ? e.name
                             : ((e && e.message) ? e.message : String(e));
                    eyeStatus('ERROR: ' + nm);
                    if (nm === 'NotAllowedError' || nm === 'SecurityError') {
                        addBubble('blue', "I'm not allowed to use the camera yet. Tap the eye and choose Allow \\u2014 a grown-up may need to switch the Camera on in Settings (Screen Time).");
                    } else if (nm === 'NotFoundError') {
                        addBubble('blue', "I can't find a camera on this tablet.");
                    } else {
                        addBubble('blue', 'My eyes would not open just now (' + nm + '). Tap the eye to try again.');
                    }
                    eyeStop();
                }).then(function () { eyeBusy = false; }, function () { eyeBusy = false; });
            }

            eyeBtn.addEventListener('click', eyeLook);
            eyeClose.addEventListener('click', eyeStop);
            eyeFlip.addEventListener('click', function () {
                eyeFacing = (eyeFacing === 'user') ? 'environment' : 'user';
                const wasOn = !!eyeStream;
                eyeStop();
                if (wasOn) eyeStart().catch(function () {});
            });
            window.addEventListener('pagehide', function () { eyeStop(); });
          })();
        }

        inputEl.focus();
    </script>
</body>
</html>
"""
