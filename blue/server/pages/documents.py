"""Extracted verbatim from bluetools.py (see blue/server/pages).

Do not import bluetools here; this module is pure data.
"""

DOCUMENT_MANAGER_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Blue Document Manager</title>
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
        body {
            font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--cream);
            color: var(--ink);
            min-height: 100vh;
            padding: 48px 20px;
            line-height: 1.55;
        }
        .container {
            max-width: 1080px;
            margin: 0 auto;
            background: var(--paper);
            border: 1px solid var(--line);
            border-radius: 12px;
            box-shadow: var(--shadow);
            overflow: hidden;
        }
        .header {
            padding: 36px 36px 28px;
            border-bottom: 1px solid var(--line);
        }
        .header::before {
            content: "";
            display: block;
            width: 56px; height: 3px;
            background: linear-gradient(90deg, var(--gold), var(--blue));
            margin-bottom: 18px;
        }
        .header h1 {
            font-family: 'Playfair Display', Georgia, serif;
            font-weight: 700;
            font-size: 2.1em;
            color: var(--ink);
            letter-spacing: -0.01em;
        }
        .header p {
            color: var(--slate);
            font-size: 1.02em;
            margin-top: 8px;
        }
        .content {
            padding: 32px 36px;
        }
        .upload-section {
            background: var(--cream);
            border: 1px dashed var(--sage);
            border-radius: 10px;
            padding: 24px;
            text-align: center;
            margin-bottom: 30px;
            transition: border-color 0.2s, background 0.2s;
        }
        .upload-section:hover {
            border-color: var(--forest);
            background: #f4f1ea;
        }
        .upload-section.dragover {
            border-color: var(--forest);
            background: #eef2ec;
        }
        .upload-section h2 {
            font-family: 'IBM Plex Mono', monospace;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: var(--forest);
            font-size: 0.8em;
            font-weight: 500;
            margin-bottom: 14px;
        }
        .file-input-wrapper {
            position: relative;
            overflow: hidden;
            display: inline-block;
        }
        .file-input-wrapper input[type=file] {
            position: absolute;
            left: -9999px;
        }
        .file-input-label {
            background: var(--ink);
            color: #fff;
            padding: 11px 26px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.95em;
            font-weight: 500;
            transition: background 0.2s;
            display: inline-block;
        }
        .file-input-label:hover {
            background: var(--forest);
        }
        .file-name {
            margin-top: 12px;
            color: var(--slate);
            font-style: italic;
            font-size: 0.9em;
        }
        .upload-btn {
            background: var(--forest);
            color: white;
            border: none;
            padding: 11px 26px;
            border-radius: 6px;
            font-size: 0.95em;
            font-weight: 500;
            cursor: pointer;
            margin-top: 14px;
            transition: background 0.2s;
        }
        .upload-btn:hover:not(:disabled) {
            background: var(--ink);
        }
        .upload-btn:disabled {
            background: #c7cdc5;
            cursor: not-allowed;
        }
        .documents-list {
            margin-top: 40px;
        }
        .documents-list h2 {
            color: var(--ink);
            margin-bottom: 20px;
            font-size: 1.4em;
            font-family: 'Playfair Display', Georgia, serif;
            font-weight: 600;
        }
        .document-item {
            background: var(--paper);
            border: 1px solid var(--line);
            border-radius: 10px;
            padding: 16px 18px;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 16px;
            transition: box-shadow 0.15s, border-color 0.15s;
        }
        .document-item:hover {
            box-shadow: var(--shadow);
            border-color: var(--sage);
        }
        .document-info {
            flex: 1 1 auto;
            min-width: 0;            /* lets long names wrap instead of pushing buttons off-screen */
        }
        .document-name {
            font-weight: 600;
            color: var(--ink);
            font-size: 1.02em;
            margin-bottom: 4px;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .document-meta {
            color: var(--slate);
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.8em;
        }
        .doc-actions {
            display: flex;
            gap: 8px;
            flex-shrink: 0;          /* buttons always stay visible */
            align-items: center;
        }
        .delete-btn {
            background: #fff;
            color: #9a3b2f;
            border: 1px solid #e2c4be;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            transition: background 0.15s, color 0.15s;
            text-decoration: none;
            font-size: 13px;
            font-weight: 500;
            white-space: nowrap;
        }
        .delete-btn:hover {
            background: #9a3b2f;
            color: #fff;
        }
        .download-btn {
            background: var(--forest);
            color: white;
            border: none;
            padding: 8px 18px;
            border-radius: 6px;
            cursor: pointer;
            transition: background 0.15s;
            text-decoration: none;
            font-size: 13px;
            font-weight: 500;
            display: inline-block;
            white-space: nowrap;
        }
        .download-btn:hover {
            background: var(--ink);
        }
        .message {
            padding: 14px 16px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-weight: 500;
            border: 1px solid transparent;
        }
        .message.success {
            background: #eef2ec;
            color: #2e4a2e;
            border-color: var(--sage);
        }
        .message.error {
            background: #f7ece9;
            color: #7a2e22;
            border-color: #e2c4be;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }
        .stat-card {
            background: var(--ink);
            color: #fff;
            padding: 24px;
            border-radius: 10px;
            text-align: center;
            border-top: 3px solid var(--gold);
        }
        .stat-number {
            font-family: 'Playfair Display', Georgia, serif;
            font-size: 2.4em;
            font-weight: 700;
            margin-bottom: 5px;
        }
        .stat-label {
            font-family: 'IBM Plex Mono', monospace;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            font-size: 0.72em;
            opacity: 0.85;
        }
        .back-link {
            display: inline-block;
            margin-top: 20px;
            color: var(--forest);
            text-decoration: none;
            font-weight: 500;
        }
        .back-link:hover {
            color: var(--ink);
            text-decoration: underline;
        }
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: var(--slate);
        }
        .empty-state-icon {
            font-size: 3em;
            margin-bottom: 20px;
            opacity: 0.6;
        }
        .breadcrumb {
            background: var(--cream);
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 12px 18px;
            margin-bottom: 25px;
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.85em;
            color: var(--slate);
        }
        .breadcrumb a {
            color: var(--forest);
            text-decoration: none;
            font-weight: 500;
        }
        .breadcrumb a:hover { text-decoration: underline; }
        .breadcrumb .sep { color: var(--sage); margin: 0 6px; }
        .layout {
            display: grid;
            grid-template-columns: 240px 1fr;
            gap: 28px;
            align-items: start;
        }
        @media (max-width: 760px) {
            .layout { grid-template-columns: 1fr; }
        }
        .sidebar {
            background: var(--cream);
            border: 1px solid var(--line);
            border-radius: 10px;
            padding: 18px;
        }
        .sidebar h3 {
            color: var(--forest);
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.78em;
            font-weight: 500;
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 0.12em;
        }
        .tree { list-style: none; }
        .tree li { margin: 2px 0; }
        .tree a {
            display: block;
            padding: 6px 10px;
            border-radius: 6px;
            color: var(--ink);
            text-decoration: none;
            font-size: 0.95em;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .tree a:hover { background: #eef2ec; }
        .tree a.active {
            background: var(--ink);
            color: #fff;
            font-weight: 500;
        }
        .folder-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 14px;
            margin-bottom: 30px;
        }
        .folder-card {
            background: var(--cream);
            border: 1px solid var(--line);
            border-radius: 10px;
            padding: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: border-color 0.15s, box-shadow 0.15s;
        }
        .folder-card:hover {
            border-color: var(--sage);
            box-shadow: var(--shadow);
        }
        .folder-card a {
            color: var(--ink);
            font-weight: 600;
            text-decoration: none;
            font-size: 1em;
            flex: 1;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .folder-card .folder-del {
            background: none;
            border: none;
            color: #9a3b2f;
            cursor: pointer;
            font-size: 1.1em;
            padding: 2px 6px;
            border-radius: 6px;
        }
        .folder-card .folder-del:hover { background: #f7ece9; }
        .newfolder-form {
            display: flex;
            gap: 10px;
            margin-bottom: 35px;
            flex-wrap: wrap;
        }
        .newfolder-form input[type=text] {
            flex: 1;
            min-width: 200px;
            padding: 12px 16px;
            border: 1px solid var(--sage);
            border-radius: 6px;
            font-size: 1em;
            font-family: inherit;
            background: var(--paper);
            color: var(--ink);
        }
        .newfolder-form input[type=text]:focus {
            outline: none;
            border-color: var(--forest);
        }
        .newfolder-form button {
            background: var(--ink);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 6px;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.2s;
        }
        .newfolder-form button:hover { background: var(--forest); }
        .section-title {
            color: var(--ink);
            font-family: 'Playfair Display', Georgia, serif;
            font-size: 1.25em;
            font-weight: 600;
            margin: 0 0 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .ic { width:1em; height:1em; vertical-align:-0.12em; margin-right:.4em;
              fill:none; stroke:currentColor; stroke-width:1.7;
              stroke-linecap:round; stroke-linejoin:round; flex:none; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/></svg>Blue Document Manager</h1>
            <p>Upload documents to teach Blue about your files</p>
        </div>

        <div class="content">
            {% if message %}
            <div class="message {{ message_type }}">
                {{ message }}
            </div>
            {% endif %}

            <div class="stats">
                <div class="stat-card">
                    <div class="stat-number">{{ document_count }}</div>
                    <div class="stat-label">Documents</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{{ folder_count }}</div>
                    <div class="stat-label">Folders</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{{ total_size }}</div>
                    <div class="stat-label">Total Size</div>
                </div>
            </div>

            <div class="breadcrumb">
                <a href="/documents?folder="><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/></svg>Library</a>
                {% for crumb in breadcrumb %}
                    <span class="sep">/</span>
                    <a href="/documents?folder={{ crumb.path|urlencode }}">{{ crumb.name }}</a>
                {% endfor %}
            </div>

            <div class="layout">
                <div class="sidebar">
                    <h3>Folders</h3>
                    <ul class="tree">
                        <li><a href="/documents?folder=" class="{{ 'active' if not current_folder else '' }}"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/></svg>Library</a></li>
                        {% for node in folder_tree %}
                        <li>
                            <a href="/documents?folder={{ node.path|urlencode }}"
                               class="{{ 'active' if node.path == current_folder else '' }}"
                               style="padding-left: {{ 10 + node.depth * 14 }}px;"
                               title="{{ node.path }}"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>{{ node.name }}</a>
                        </li>
                        {% endfor %}
                    </ul>
                </div>

                <div class="main">
                    <h2 class="section-title"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>Folders in this area</h2>
                    {% if subfolders %}
                    <div class="folder-grid">
                        {% for sub in subfolders %}
                        <div class="folder-card">
                            <a href="/documents?folder={{ sub.path|urlencode }}"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>{{ sub.name }}</a>
                            <form method="POST" action="/documents/folder/delete" style="margin:0;"
                                  onsubmit="return confirm('Delete folder {{ sub.name }}? It must be empty.');">
                                <input type="hidden" name="folder" value="{{ sub.path }}">
                                <input type="hidden" name="back" value="{{ current_folder }}">
                                <button type="submit" class="folder-del" title="Delete folder">✕</button>
                            </form>
                        </div>
                        {% endfor %}
                    </div>
                    {% else %}
                    <p style="color:#999; margin-bottom: 25px;">No subfolders here yet.</p>
                    {% endif %}

                    <form method="POST" action="/documents" class="newfolder-form">
                        <input type="hidden" name="action" value="create_folder">
                        <input type="hidden" name="parent" value="{{ current_folder }}">
                        <input type="text" name="name" placeholder="New folder name (e.g. Publications)" required>
                        <button type="submit">+ Add Folder</button>
                    </form>

                    <div class="upload-section" id="dropZone">
                        <h2><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5M5 20h14"/></svg>Upload to {{ current_folder if current_folder else 'Library root' }}</h2>
                        <p style="color: #666; margin-bottom: 20px;">
                            <strong>Drag &amp; drop a file here</strong> — or use the button below.<br>
                            Supported: PDF, Word (.doc, .docx), Text (.txt, .md)
                        </p>
                        <form method="POST" enctype="multipart/form-data" id="uploadForm">
                            <input type="hidden" name="action" value="upload">
                            <input type="hidden" name="folder" value="{{ current_folder }}">
                            <div class="file-input-wrapper">
                                <input type="file" name="file" id="fileInput" accept=".pdf,.doc,.docx,.txt,.md" required>
                                <label for="fileInput" class="file-input-label">Choose File</label>
                            </div>
                            <div class="file-name" id="fileName">No file chosen</div>
                            <br>
                            <button type="submit" class="upload-btn" id="uploadBtn">Upload & Index</button>
                        </form>
                    </div>

                    <div class="documents-list">
                        <h2 class="section-title"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>Documents in this folder</h2>
                        {% if documents %}
                            {% for doc in documents %}
                            <div class="document-item">
                                <div class="document-info">
                                    <div class="document-name">{{ doc.filename }}</div>
                                    <div class="document-meta">
                                        Uploaded: {{ doc.uploaded_at }} | Size: {{ doc.size }}
                                        {% if doc.created_by_blue %}
                                        <span style="color: #667eea; font-weight: 600;"> • Created by Blue</span>
                                        {% endif %}
                                    </div>
                                </div>
                                <div class="doc-actions">
                                    <a href="/documents/download?folder={{ current_folder|urlencode }}&filename={{ doc.filename|urlencode }}" class="download-btn">
                                        Download
                                    </a>
                                    <form method="POST" action="/documents/delete" style="display: inline; margin: 0;">
                                        <input type="hidden" name="folder" value="{{ current_folder }}">
                                        <input type="hidden" name="filename" value="{{ doc.filename }}">
                                        <button type="submit" class="delete-btn" onclick="return confirm('Delete this document?')">
                                            Delete
                                        </button>
                                    </form>
                                </div>
                            </div>
                            {% endfor %}
                        {% else %}
                            <div class="empty-state">
                                <div class="empty-state-icon"><svg viewBox="0 0 24 24" width="42" height="42" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/></svg></div>
                                <h3>No documents in this folder</h3>
                                <p>Upload one above, or pick another folder.</p>
                            </div>
                        {% endif %}
                    </div>
                </div>
            </div>

            <a href="/" class="back-link">← Back to main page</a>
            <a href="/perspective" class="back-link" style="margin-left: 24px;"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 4-6 8-6s8 2 8 6"/></svg>My Perspective Profile</a>
        </div>
    </div>

    <script>
        const fileInput = document.getElementById('fileInput');
        const fileNameEl = document.getElementById('fileName');
        const dropZone = document.getElementById('dropZone');
        const uploadForm = document.getElementById('uploadForm');
        const ALLOWED = ['pdf', 'doc', 'docx', 'txt', 'md'];

        fileInput.addEventListener('change', function(e) {
            fileNameEl.style.color = '#666';
            fileNameEl.textContent = e.target.files[0] ? e.target.files[0].name : 'No file chosen';
        });

        uploadForm.addEventListener('submit', function() {
            const btn = document.getElementById('uploadBtn');
            btn.disabled = true;
            btn.textContent = 'Uploading...';
        });

        // Drag-and-drop: drop a file straight from Explorer without ever
        // opening the native "Choose File" dialog.
        function assignDroppedFile(file) {
            const ext = file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : '';
            if (ALLOWED.indexOf(ext) === -1) {
                fileNameEl.style.color = '#dc3545';
                fileNameEl.textContent = 'Unsupported file type: .' + ext;
                return;
            }
            const dt = new DataTransfer();
            dt.items.add(file);
            fileInput.files = dt.files;
            fileNameEl.style.color = '#28a745';
            fileNameEl.textContent = file.name + ' — ready, click "Upload & Index"';
        }

        function highlight(e) {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.add('dragover');
        }
        dropZone.addEventListener('dragenter', highlight);
        dropZone.addEventListener('dragover', highlight);
        dropZone.addEventListener('dragleave', function(e) {
            e.preventDefault();
            e.stopPropagation();
            if (!dropZone.contains(e.relatedTarget)) {
                dropZone.classList.remove('dragover');
            }
        });
        dropZone.addEventListener('drop', function(e) {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove('dragover');
            const files = e.dataTransfer && e.dataTransfer.files;
            if (files && files.length) {
                assignDroppedFile(files[0]);
            }
        });

        // A file dropped outside the box would otherwise make the browser
        // navigate away from this page — swallow those stray drops.
        window.addEventListener('dragover', function(e) { e.preventDefault(); });
        window.addEventListener('drop', function(e) { e.preventDefault(); });
    </script>
</body>
</html>
"""
