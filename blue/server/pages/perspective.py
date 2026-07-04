"""Extracted verbatim from bluetools.py (see blue/server/pages).

Do not import bluetools here; this module is pure data.
"""

PERSPECTIVE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>My Perspective Profile</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
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
        body { font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: var(--cream); color: var(--ink); min-height: 100vh; padding: 48px 20px; line-height: 1.55; }
        .container { max-width: 900px; margin: 0 auto; background: var(--paper); border: 1px solid var(--line);
                     border-radius: 12px; box-shadow: var(--shadow); overflow: hidden; }
        .header { padding: 36px 36px 28px; border-bottom: 1px solid var(--line); }
        .header::before { content: ""; display: block; width: 56px; height: 3px;
                          background: linear-gradient(90deg, var(--gold), var(--blue)); margin-bottom: 18px; }
        .header h1 { font-family: 'Playfair Display', Georgia, serif; font-weight: 700; font-size: 1.9em;
                     color: var(--ink); letter-spacing: -0.01em; margin-bottom: 8px; }
        .header p { color: var(--slate); }
        .content { padding: 32px 36px; }
        .meta { background: var(--cream); border: 1px solid var(--line); border-radius: 8px; padding: 12px 16px;
                color: var(--slate); font-family: 'IBM Plex Mono', monospace; font-size: 0.82em; margin-bottom: 20px; }
        .meta b { color: var(--forest); }
        textarea { width: 100%; min-height: 460px; padding: 18px; border: 1px solid var(--sage);
                   border-radius: 8px; font-size: 0.98em; line-height: 1.6; resize: vertical;
                   font-family: 'IBM Plex Sans', system-ui, sans-serif; color: var(--ink); background: var(--paper); }
        textarea:focus { outline: none; border-color: var(--forest); }
        .actions { display: flex; gap: 12px; margin-top: 18px; flex-wrap: wrap; align-items: center; }
        .btn { border: none; padding: 12px 26px; border-radius: 6px; font-weight: 500;
               font-size: 0.95em; cursor: pointer; text-decoration: none; display: inline-block; transition: background 0.2s; }
        .btn-save { background: var(--ink); color: #fff; }
        .btn-save:hover { background: var(--forest); }
        .btn-regen { background: #fff; color: var(--forest); border: 1px solid var(--sage); }
        .btn-regen:hover { background: var(--cream); }
        .hint { color: var(--slate); font-size: 0.85em; }
        .message { padding: 14px 16px; border-radius: 8px; margin-bottom: 20px; font-weight: 500; border: 1px solid transparent; }
        .message.success { background: #eef2ec; color: #2e4a2e; border-color: var(--sage); }
        .message.error { background: #f7ece9; color: #7a2e22; border-color: #e2c4be; }
        .message.info { background: #eef3fb; color: #2a4a7a; border-color: #c4d6f2; }
        .back-link { display: inline-block; margin-top: 22px; color: var(--forest); text-decoration: none; font-weight: 500; }
        .back-link:hover { color: var(--ink); text-decoration: underline; }
        .ic { width:1em; height:1em; vertical-align:-0.12em; margin-right:.4em;
              fill:none; stroke:currentColor; stroke-width:1.7;
              stroke-linecap:round; stroke-linejoin:round; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 4-6 8-6s8 2 8 6"/></svg>My Perspective Profile</h1>
            <p>How Blue understands your thinking — distilled from the {{ owner_name }} folder. Edit it freely; your edits stick.</p>
        </div>
        <div class="content">
            {% if message %}<div class="message {{ message_type }}">{{ message }}</div>{% endif %}

            <div class="meta">
                {% if has_profile %}
                    <b>Sources:</b> {{ source_docs|join(', ') if source_docs else 'none' }}<br>
                    <b>{{ 'Edited by you' if user_edited else 'Generated' }}:</b> {{ stamp }}
                    {% if user_edited %} &nbsp;•&nbsp; <span style="color:#7a5b00;">manual edits are preserved (auto-refresh won't overwrite)</span>{% endif %}
                {% else %}
                    No profile yet. Click <b>Regenerate from my writing</b> to build it from your {{ owner_name }} folder.
                {% endif %}
            </div>

            <form method="POST" action="/perspective">
                <textarea name="profile" placeholder="Blue hasn't learned your perspective yet — regenerate to build it, or write/paste your own here and save.">{{ profile }}</textarea>
                <div class="actions">
                    <button type="submit" name="action" value="save" class="btn btn-save"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8M7 3v5h8"/></svg>Save my edits</button>
                    <button type="submit" name="action" value="regenerate" class="btn btn-regen"
                            onclick="return confirm('Rebuild the profile from scratch by reading your {{ owner_name }} folder? This replaces the current text and can take a minute.');">
                        <svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.6-6.4M21 4v4h-4"/></svg>Regenerate from my writing
                    </button>
                    <span class="hint">Regenerating reads each document, so it may take a minute.</span>
                </div>
            </form>

            <a href="/documents" class="back-link">← Back to documents</a>
            <a href="/perspective/blue" class="back-link" style="margin-left: 24px;"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/></svg>Blue's Perspective</a>
        </div>
    </div>
</body>
</html>
"""

BLUE_PROFILE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Blue's Perspective</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
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
        body { font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: var(--cream); color: var(--ink); min-height: 100vh; padding: 48px 20px; line-height: 1.55; }
        .container { max-width: 900px; margin: 0 auto; background: var(--paper); border: 1px solid var(--line);
                     border-radius: 12px; box-shadow: var(--shadow); overflow: hidden; }
        .header { padding: 36px 36px 28px; border-bottom: 1px solid var(--line); }
        .header::before { content: ""; display: block; width: 56px; height: 3px;
                          background: linear-gradient(90deg, var(--blue), var(--gold)); margin-bottom: 18px; }
        .header h1 { font-family: 'Playfair Display', Georgia, serif; font-weight: 700; font-size: 1.9em;
                     color: var(--ink); letter-spacing: -0.01em; margin-bottom: 8px; }
        .header p { color: var(--slate); }
        .content { padding: 32px 36px; }
        .meta { background: var(--cream); border: 1px solid var(--line); border-radius: 8px; padding: 12px 16px;
                color: var(--slate); font-family: 'IBM Plex Mono', monospace; font-size: 0.82em; margin-bottom: 20px; }
        .meta b { color: var(--blue); }
        textarea { width: 100%; min-height: 440px; padding: 18px; border: 1px solid var(--sage);
                   border-radius: 8px; font-size: 0.98em; line-height: 1.6; resize: vertical;
                   font-family: 'IBM Plex Sans', system-ui, sans-serif; color: var(--ink); background: var(--paper); }
        textarea:focus { outline: none; border-color: var(--blue); }
        .actions { display: flex; gap: 12px; margin-top: 18px; flex-wrap: wrap; align-items: center; }
        .btn { border: none; padding: 12px 26px; border-radius: 6px; font-weight: 500;
               font-size: 0.95em; cursor: pointer; text-decoration: none; display: inline-block; transition: background 0.2s; }
        .btn-save { background: var(--ink); color: #fff; }
        .btn-save:hover { background: var(--forest); }
        .btn-evolve { background: #fff; color: var(--blue); border: 1px solid #c4d6f2; }
        .btn-evolve:hover { background: #eef3fb; }
        .hint { color: var(--slate); font-size: 0.85em; }
        .message { padding: 14px 16px; border-radius: 8px; margin-bottom: 20px; font-weight: 500; border: 1px solid transparent; }
        .message.success { background: #eef2ec; color: #2e4a2e; border-color: var(--sage); }
        .message.error { background: #f7ece9; color: #7a2e22; border-color: #e2c4be; }
        .nav { margin-top: 22px; }
        .nav a { color: var(--forest); text-decoration: none; font-weight: 500; margin-right: 22px; }
        .nav a:hover { color: var(--ink); text-decoration: underline; }
        .ic { width:1em; height:1em; vertical-align:-0.12em; margin-right:.4em;
              fill:none; stroke:currentColor; stroke-width:1.7;
              stroke-linecap:round; stroke-linejoin:round; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/></svg>Blue's Perspective</h1>
            <p>Who Blue is — his own evolving character. This shapes how he speaks when he's being himself (not writing as you). Edit it freely; evolving builds on whatever's here.</p>
        </div>
        <div class="content">
            {% if message %}<div class="message {{ message_type }}">{{ message }}</div>{% endif %}

            <div class="meta">
                <b>{{ 'Edited by you' if user_edited else ('Evolved' if evolution_count else 'Seeded from identity note') }}:</b> {{ stamp }}
                &nbsp;•&nbsp; <b>Evolutions:</b> {{ evolution_count }}
                {% if user_edited %} &nbsp;•&nbsp; <span style="color:#7a5b00;">your edits carry forward into the next evolution</span>{% endif %}
            </div>

            <form method="POST" action="/perspective/blue">
                <textarea name="profile" placeholder="Blue's sense of himself...">{{ profile }}</textarea>
                <div class="actions">
                    <button type="submit" name="action" value="save" class="btn btn-save"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8M7 3v5h8"/></svg>Save edits</button>
                    <button type="submit" name="action" value="evolve" class="btn btn-evolve"
                            onclick="return confirm('Evolve Blue\\'s perspective now from his recent experiences? This builds on the current text and can take a minute.');">
                        <svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 22V11M12 11C12 7 9 4 4 4c0 5 3 7 8 7zM12 11c0-3 2-5 6-5 0 4-2 6-6 6z"/></svg>Evolve now
                    </button>
                    <span class="hint">Evolving reads his memories, recent days, and library — may take a minute.</span>
                </div>
            </form>

            <div class="nav">
                <a href="/perspective"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 4-6 8-6s8 2 8 6"/></svg>My (Alex's) Perspective</a>
                <a href="/documents"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/></svg>Documents</a>
            </div>
        </div>
    </div>
</body>
</html>
"""
