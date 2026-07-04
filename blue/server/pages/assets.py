"""Extracted verbatim from bluetools.py (see blue/server/pages).

Do not import bluetools here; this module is pure data.
"""

BLUE_CSS = r"""
/* ============================================================================
   Blue AI Robot System — "Midnight Glass" design system.

   Every page defines the same CSS variables (--cream, --ink, --paper, ...)
   with the old light "cream" values inline. This sheet makes MIDNIGHT the
   default by overriding those variables (and the handful of hardcoded
   surfaces) under `:root:not([data-theme="light"])`, which out-specifies the
   pages' own `:root` blocks. Choosing the light theme (the floating toggle,
   or kid mode) simply sets data-theme="light" — every rule here stands down
   and the pages' original cream styling shows through untouched.
   ========================================================================== */
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html { -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
       text-rendering: optimizeLegibility; scroll-behavior: smooth; }
*:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; border-radius: 4px; }
* { scrollbar-width: thin; scrollbar-color: var(--sage) transparent; }
::-webkit-scrollbar { width: 11px; height: 11px; }
::-webkit-scrollbar-thumb { background: var(--sage); border-radius: 7px;
    border: 3px solid transparent; background-clip: content-box; }
::-webkit-scrollbar-thumb:hover { background: var(--forest); background-clip: content-box; }
::selection { background: rgba(96,165,250,0.35); }
:root[data-theme="light"] ::selection { background: rgba(212,175,55,0.28); }

/* ===== MIDNIGHT GLASS (default theme) ================================== */
:root:not([data-theme="light"]) {
    /* Legacy palette names, remapped so every page flips at once. */
    --cream:#070d1a;                    /* page background       */
    --paper:rgba(17,28,50,0.72);        /* glass card surface    */
    --ink:#e8eefb;                      /* main text             */
    --forest:#7fb2ff;                   /* old green accent → blue */
    --sage:#3d5580;                     /* soft accent / scrollbars */
    --slate:#8fa3c7;                    /* secondary text        */
    --blue:#60a5fa; --gold:#fbbf24;
    --line:rgba(148,184,255,0.16);
    --shadow:0 14px 40px rgba(0,0,0,0.45);
    /* New tokens for this sheet's own components. */
    --mg-cyan:#5eead4; --mg-violet:#a78bfa;
    --mg-grad:linear-gradient(135deg,#2563eb,#0891b2);
    --mg-glass:rgba(148,184,255,0.06); --mg-glass2:rgba(148,184,255,0.11);
    color-scheme: dark;
}
:root:not([data-theme="light"]) body {
    background:
        radial-gradient(1100px 650px at 82% -10%, #14264d 0%, transparent 60%),
        radial-gradient(900px 600px at -12% 38%, #0e2a33 0%, transparent 55%),
        #070d1a fixed;
    color: var(--ink);
}
/* Display face: Space Grotesk replaces the serif on midnight. */
:root:not([data-theme="light"]) h1,
:root:not([data-theme="light"]) h2,
:root:not([data-theme="light"]) h3,
:root:not([data-theme="light"]) .wordmark .name,
:root:not([data-theme="light"]) .tile h2,
:root:not([data-theme="light"]) .about h2 {
    font-family: 'Space Grotesk', 'IBM Plex Sans', -apple-system, sans-serif !important;
    letter-spacing: -0.02em;
}
:root:not([data-theme="light"]) .wordmark .name {
    background: linear-gradient(90deg,#dbeafe,#5eead4);
    -webkit-background-clip: text; background-clip: text; color: transparent;
}
:root:not([data-theme="light"]) .wordmark .sys { color: var(--slate); }
/* Glass surfaces: cards & panels blur what's behind them. */
:root:not([data-theme="light"]) .tile,
:root:not([data-theme="light"]) .card,
:root:not([data-theme="light"]) .about,
:root:not([data-theme="light"]) .modal,
:root:not([data-theme="light"]) .panel,
:root:not([data-theme="light"]) .day-panel,
:root:not([data-theme="light"]) .stat-card,
:root:not([data-theme="light"]) .chip {
    backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
}
:root:not([data-theme="light"]) .tile:hover {
    border-color: rgba(94,234,212,0.4);
    box-shadow: 0 18px 44px rgba(0,0,0,0.55);
}
/* Strong-background elements (were forest green): electric gradient + glow. */
:root:not([data-theme="light"]) .btn-primary,
:root:not([data-theme="light"]) .btn-save,
:root:not([data-theme="light"]) .sendbtn,
:root:not([data-theme="light"]) .file-input-label,
:root:not([data-theme="light"]) .upload-btn,
:root:not([data-theme="light"]) .download-btn,
:root:not([data-theme="light"]) .newfolder-form button,
:root:not([data-theme="light"]) button.primary,
:root:not([data-theme="light"]) .tree a.active,
:root:not([data-theme="light"]) .cell.today .num,
:root:not([data-theme="light"]) .tab.active,
:root:not([data-theme="light"]) .row.user .bubble,
:root:not([data-theme="light"]) .tile-cta {
    background: var(--mg-grad) !important; color: #f4f9ff !important;
    border-color: transparent !important;
}
:root:not([data-theme="light"]) .btn-primary:hover,
:root:not([data-theme="light"]) .sendbtn:hover:not(:disabled),
:root:not([data-theme="light"]) .file-input-label:hover,
:root:not([data-theme="light"]) .upload-btn:hover:not(:disabled),
:root:not([data-theme="light"]) button.primary:hover,
:root:not([data-theme="light"]) .newfolder-form button:hover {
    background: linear-gradient(135deg,#3b82f6,#06b6d4) !important;
    box-shadow: 0 6px 22px rgba(37,99,235,0.45);
}
/* Light accent chips → glass surfaces so their text stays legible. */
:root:not([data-theme="light"]) .avatar,
:root:not([data-theme="light"]) .photo,
:root:not([data-theme="light"]) .ev,
:root:not([data-theme="light"]) .c-rel,
:root:not([data-theme="light"]) .badge,
:root:not([data-theme="light"]) .ticon,
:root:not([data-theme="light"]) .empty-state-icon {
    background: var(--mg-glass2) !important; color: var(--forest);
}
:root:not([data-theme="light"]) .upload-section { background: var(--mg-glass) !important; }
:root:not([data-theme="light"]) .chip .dot,
:root:not([data-theme="light"]) .chip i { box-shadow: 0 0 8px currentColor; }
/* Home "about" prose hardcodes a dark green — lift it on midnight. */
:root:not([data-theme="light"]) .about p { color: #b9c6e2; }
:root:not([data-theme="light"]) .about p.lead { color: var(--slate); }
/* Document manager stat cards hardcode a pale gradient with white numbers. */
:root:not([data-theme="light"]) .stat-card {
    background: var(--mg-grad) !important; color: #f4f9ff !important;
}
/* Calendar: out-of-month cells hardcode cream; danger buttons hardcode white. */
:root:not([data-theme="light"]) .cell.other {
    background: rgba(148,184,255,0.045) !important; color: #4a5d80 !important;
}
:root:not([data-theme="light"]) .btn-danger {
    background: rgba(248,113,113,0.12) !important; color: #f87171 !important;
    border-color: rgba(248,113,113,0.35) !important;
}
/* Form controls on glass. */
:root:not([data-theme="light"]) input[type="text"],
:root:not([data-theme="light"]) input[type="password"],
:root:not([data-theme="light"]) input[type="search"],
:root:not([data-theme="light"]) input[type="email"],
:root:not([data-theme="light"]) input[type="number"],
:root:not([data-theme="light"]) input[type="date"],
:root:not([data-theme="light"]) input[type="time"],
:root:not([data-theme="light"]) textarea,
:root:not([data-theme="light"]) select {
    background: var(--mg-glass); color: var(--ink);
    border-color: var(--line);
}
:root:not([data-theme="light"]) a { color: var(--forest); }
:root:not([data-theme="light"]) code { background: var(--mg-glass2); color: var(--mg-cyan); }

/* ===== Floating light/dark toggle (injected by blue.js) ================ */
.blue-theme-toggle {
    position: fixed; bottom: calc(18px + env(safe-area-inset-bottom, 0px));
    right: calc(18px + env(safe-area-inset-right, 0px)); z-index: 9999;
    width: 44px; height: 44px; border-radius: 50%;
    background: var(--paper); color: var(--forest);
    border: 1px solid var(--line); box-shadow: var(--shadow);
    backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
    display: flex; align-items: center; justify-content: center; cursor: pointer;
    transition: transform .15s ease, color .2s, background .2s;
}
.blue-theme-toggle:hover { transform: translateY(-2px); color: var(--ink); }
.blue-theme-toggle svg { width: 20px; height: 20px; fill: none; stroke: currentColor;
    stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }

/* ===== Site-wide nav drawer (injected by blue.js) ======================= */
.blue-nav-fab {
    position: fixed; top: calc(14px + env(safe-area-inset-top, 0px));
    left: calc(14px + env(safe-area-inset-left, 0px)); z-index: 9999;
    width: 44px; height: 44px; border-radius: 14px;
    background: var(--paper); color: var(--forest);
    border: 1px solid var(--line); box-shadow: var(--shadow);
    backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
    display: flex; align-items: center; justify-content: center; cursor: pointer;
    transition: transform .15s ease;
}
.blue-nav-fab:hover { transform: translateY(-2px); }
.blue-nav-fab svg { width: 20px; height: 20px; fill: none; stroke: currentColor;
    stroke-width: 1.8; stroke-linecap: round; }
.blue-nav-scrim {
    position: fixed; inset: 0; z-index: 9998; background: rgba(3,7,15,0.55);
    opacity: 0; pointer-events: none; transition: opacity .2s ease;
}
.blue-nav-drawer {
    position: fixed; top: 0; bottom: 0; left: 0; z-index: 9999;
    width: min(300px, 84vw); padding: 18px 14px calc(18px + env(safe-area-inset-bottom, 0px));
    padding-top: calc(18px + env(safe-area-inset-top, 0px));
    background: var(--cream); border-right: 1px solid var(--line);
    box-shadow: 0 0 60px rgba(0,0,0,0.5);
    transform: translateX(-102%); transition: transform .22s ease;
    overflow-y: auto; display: flex; flex-direction: column; gap: 3px;
}
:root:not([data-theme="light"]) .blue-nav-drawer {
    background: rgba(9,16,32,0.92);
    backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
}
.blue-nav-open .blue-nav-drawer { transform: none; }
.blue-nav-open .blue-nav-scrim { opacity: 1; pointer-events: auto; }
.blue-nav-drawer .bn-title {
    font-family: 'Space Grotesk', 'IBM Plex Sans', sans-serif; font-weight: 700;
    font-size: 19px; color: var(--ink); padding: 6px 12px 14px;
    display: flex; align-items: center; gap: 10px;
}
.blue-nav-drawer .bn-orb { width: 22px; height: 22px; border-radius: 50%;
    background: radial-gradient(circle at 32% 28%, #93c5fd, #2563eb 65%);
    box-shadow: 0 0 14px rgba(96,165,250,0.7); }
:root[data-theme="light"] .blue-nav-drawer .bn-orb { box-shadow: none; }
.blue-nav-drawer .bn-sec {
    font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace; font-size: 10.5px;
    letter-spacing: 0.2em; text-transform: uppercase; color: var(--slate);
    padding: 14px 12px 5px;
}
.blue-nav-drawer a {
    display: flex; align-items: center; gap: 11px; text-decoration: none;
    color: var(--ink); font-size: 15px; font-weight: 500;
    padding: 11px 12px; border-radius: 12px; min-height: 44px;
}
.blue-nav-drawer a:hover { background: var(--mg-glass2, rgba(0,0,0,0.05)); }
.blue-nav-drawer a.on { background: var(--mg-grad, #1a2e1a); color: #fff; }
.blue-nav-drawer a svg { width: 19px; height: 19px; flex: none; fill: none;
    stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }

/* Gentle entrance for cards/containers — a touch of life without bounce. */
@keyframes blueFadeUp { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.container, .card, .grid, .day-panel { animation: blueFadeUp .28s ease both; }
@media (prefers-reduced-motion: reduce) { *, *::before { animation: none !important; transition: none !important; } }

/* ===== Phone-friendly ==================================================== */
@media (max-width: 640px) {
    /* iOS zooms in when a focused field is under 16px — pin inputs to 16px. */
    input, textarea, select { font-size: 16px !important; }
    /* Collapse multi-column layouts to a single column. */
    .tiles, .folder-grid, .stats, .grid { grid-template-columns: 1fr !important; }
    .layout { grid-template-columns: 1fr !important; }
    .row2 { flex-direction: column !important; gap: 0 !important; }
    /* Modals fill the screen and anchor near the top. */
    .overlay { padding: 8px !important; align-items: flex-start !important; }
    .modal { max-width: 100% !important; padding: 18px !important; }
    /* Comfortable tap targets. */
    .btn, .tab, .iconbtn, .sendbtn, .file-input-label, .download-btn,
    .delete-btn, .btn-icon, .btn-primary {
        min-height: 42px; display: inline-flex; align-items: center; justify-content: center; }
    /* Trim oversized desktop padding. */
    .content { padding: 20px 16px !important; }
    .header { padding: 22px 18px 16px !important; }
    /* Scale big headings down. */
    .wordmark .name { font-size: 2em !important; }
    h1 { font-size: 1.55em !important; }
    /* Keep the month grid usable on a narrow screen. */
    .cell { min-height: 48px !important; padding: 3px !important; }
    .cell .num { font-size: 0.78em !important; }
    .ev { font-size: 0.56em !important; padding: 1px 4px !important; }
    /* Long emails / filenames must wrap, not overflow. */
    .c-sub, .document-name, .ev-time, .tagline { overflow-wrap: anywhere; }
    .blue-theme-toggle { bottom: calc(12px + env(safe-area-inset-bottom, 0px)); right: 12px; }
    .blue-nav-fab { top: calc(10px + env(safe-area-inset-top, 0px)); left: 10px; }
}
"""

BLUE_JS = r"""
(function(){
  // MIDNIGHT GLASS is the default. data-theme="light" restores the original
  // cream look. Kid mode (Vilda's chat) is pinned to light so her pastel UI
  // never changes — no toggle, no nav drawer on her screen.
  var KID = !!(document.body && document.body.classList.contains('kid'));
  var stored = null;
  try { stored = localStorage.getItem('blue-theme'); } catch(e){}
  function setTheme(t){
    if (t === 'light') document.documentElement.setAttribute('data-theme','light');
    else document.documentElement.removeAttribute('data-theme');
    var m = document.querySelector('meta[name="theme-color"]');
    if (!m) { m = document.createElement('meta'); m.name = 'theme-color';
              document.head.appendChild(m); }
    m.content = (t === 'light') ? '#faf8f4' : '#070d1a';
  }
  setTheme(KID ? 'light' : (stored === 'light' ? 'light' : 'midnight'));
  if (KID) return;

  function cur(){ return document.documentElement.getAttribute('data-theme')==='light' ? 'light':'midnight'; }

  var SUN='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.4 1.4M17.6 17.6L19 19M19 5l-1.4 1.4M6.4 17.6L5 19"/></svg>';
  var MOON='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/></svg>';
  function buildToggle(){
    if (document.querySelector('.blue-theme-toggle')) return;
    var b=document.createElement('button');
    b.className='blue-theme-toggle'; b.type='button';
    b.setAttribute('aria-label','Switch between midnight and light theme'); b.title='Midnight / light';
    function paint(){ b.innerHTML = cur()==='midnight' ? SUN : MOON; }
    paint();
    b.addEventListener('click', function(){
      var next = cur()==='midnight' ? 'light':'midnight';
      setTheme(next);
      try { localStorage.setItem('blue-theme', next); } catch(e){}
      paint();
    });
    document.body.appendChild(b);
  }

  // ---- Site-wide navigation drawer -------------------------------------
  var ICONS = {
    home:'<svg viewBox="0 0 24 24"><path d="M3 11 12 3l9 8"/><path d="M5 10v10h14V10"/></svg>',
    chat:'<svg viewBox="0 0 24 24"><path d="M21 12a8 8 0 0 1-11.5 7.2L4 20l1-4.5A8 8 0 1 1 21 12z"/></svg>',
    duet:'<svg viewBox="0 0 24 24"><path d="M7 9a5 5 0 0 1 10 0c0 3-3 4-3 6H10c0-2-3-3-3-6z"/><path d="M9 20h6"/></svg>',
    lib:'<svg viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/></svg>',
    cal:'<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18M8 2v4M16 2v4"/></svg>',
    ppl:'<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 4-6 8-6s8 2 8 6"/></svg>',
    eye:'<svg viewBox="0 0 24 24"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>',
    persp:'<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    bot:'<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/></svg>',
    tune:'<svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="8" cy="18" r="2"/></svg>'
  };
  var NAV = [
    ['Talk', [['/', 'Home', 'home'], ['/chat', 'Chat with Blue', 'chat'],
              ['/hexia', 'Chat with Hexia', 'chat'], ['/duet', 'Duet', 'duet']]],
    ['Know', [['/documents', 'Documents', 'lib'], ['/calendar', 'Calendar', 'cal'],
              ['/contacts', 'Contacts', 'ppl'], ['/visual', 'Visual memory', 'eye'],
              ['/perspective', 'Perspective', 'persp']]],
    ['Robots', [['/heads', 'Robot heads', 'bot'], ['/head', "Tune Blue's head", 'tune'],
                ['/head/hexia', "Tune Hexia's head", 'tune']]]
  ];
  function buildNav(){
    if (location.pathname === '/login') return;
    if (document.querySelector('.blue-nav-fab')) return;
    var fab=document.createElement('button');
    fab.className='blue-nav-fab'; fab.type='button';
    fab.setAttribute('aria-label','Open navigation'); fab.title='Menu';
    fab.innerHTML='<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></svg>';
    var scrim=document.createElement('div'); scrim.className='blue-nav-scrim';
    var d=document.createElement('nav'); d.className='blue-nav-drawer';
    d.setAttribute('aria-label','Blue navigation');
    var html='<div class="bn-title"><span class="bn-orb"></span>Blue</div>';
    for (var s=0; s<NAV.length; s++){
      html+='<div class="bn-sec">'+NAV[s][0]+'</div>';
      var items=NAV[s][1];
      for (var i=0; i<items.length; i++){
        var on = location.pathname === items[i][0] ? ' class="on"' : '';
        html+='<a href="'+items[i][0]+'"'+on+'>'+ICONS[items[i][2]]+items[i][1]+'</a>';
      }
    }
    d.innerHTML=html;
    function close(){ document.documentElement.classList.remove('blue-nav-open'); }
    fab.addEventListener('click', function(){
      document.documentElement.classList.toggle('blue-nav-open');
    });
    scrim.addEventListener('click', close);
    document.addEventListener('keydown', function(e){ if (e.key==='Escape') close(); });
    document.body.appendChild(fab);
    document.body.appendChild(scrim);
    document.body.appendChild(d);
  }

  function build(){ buildToggle(); buildNav(); }
  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded', build);
  else build();
})();
"""
