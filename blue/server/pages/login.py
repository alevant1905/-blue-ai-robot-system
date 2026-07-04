"""Extracted verbatim from bluetools.py (see blue/server/pages).

Do not import bluetools here; this module is pure data.
"""

_LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Sign in to Blue</title>
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
               background: var(--cream); color: var(--ink); min-height: 100vh;
               display: flex; align-items: center; justify-content: center; padding: 24px; line-height: 1.55; }
        .card { background: var(--paper); border: 1px solid var(--line); border-radius: 12px;
                box-shadow: var(--shadow); padding: 40px; max-width: 380px; width: 100%; }
        .card::before { content: ""; display: block; width: 56px; height: 3px;
                        background: linear-gradient(90deg, var(--gold), var(--blue)); margin-bottom: 20px; }
        h1 { font-family: 'Playfair Display', Georgia, serif; font-weight: 700; font-size: 1.6em;
             color: var(--ink); margin-bottom: 6px; letter-spacing: -0.01em; }
        p.sub { color: var(--slate); font-size: 0.95em; margin-bottom: 24px; }
        label { font-family: 'IBM Plex Mono', monospace; font-size: 0.72em; text-transform: uppercase;
                letter-spacing: 0.12em; color: var(--forest); display: block; margin-bottom: 8px; }
        input[type=password] { width: 100%; padding: 13px 15px; border: 1px solid var(--sage);
               border-radius: 8px; font-family: inherit; font-size: 1em; color: var(--ink); background: var(--paper); }
        input[type=password]:focus { outline: none; border-color: var(--forest); }
        button { margin-top: 18px; width: 100%; padding: 13px; border: none; border-radius: 8px;
                 background: var(--ink); color: #fff; font-weight: 500; font-size: 0.98em; cursor: pointer;
                 transition: background 0.2s; }
        button:hover { background: var(--forest); }
        .err { margin-top: 16px; background: #f7ece9; color: #7a2e22; border: 1px solid #e2c4be;
               border-radius: 8px; padding: 11px 14px; font-size: 0.9em; }
    </style>
</head>
<body>
    <div class="card">
        <h1>Sign in to Blue</h1>
        <p class="sub">Enter the access password to continue.</p>
        <form method="POST" action="/login">
            <input type="hidden" name="next" value="{{ next }}">
            <label for="password">Password</label>
            <input type="password" id="password" name="password" autofocus autocomplete="current-password">
            <button type="submit">Sign in</button>
        </form>
        {% if error %}<div class="err">{{ error }}</div>{% endif %}
    </div>
</body>
</html>
"""
