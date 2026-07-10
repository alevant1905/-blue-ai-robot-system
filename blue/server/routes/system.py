"""System routes extracted verbatim from bluetools.py: home page (/),
/health, /stats, /memory/*, /api/rag/* and the shared theme assets.

All shared state stays in bluetools and is read via bt.<name> at
request time.
"""
import bluetools as bt
from flask import Response, jsonify, request

from blue.server.pages.assets import BLUE_CSS, BLUE_JS


def register(app):
    @app.route('/assets/blue.css')
    def asset_blue_css():
        return Response(BLUE_CSS, mimetype="text/css")

    @app.route('/assets/blue.js')
    def asset_blue_js():
        return Response(BLUE_JS, mimetype="application/javascript")

    # ===== Memory Management Endpoints =====

    @app.route('/memory/stats', methods=['GET'])


    def memory_stats():
        """Get statistics about stored conversations"""
        if bt.ENHANCED_MEMORY_AVAILABLE and bt.memory_system:
            try:
                summary = bt.memory_system.get_memory_summary()
                if summary.get("error"):
                    return jsonify({"error": summary["error"]}), 500
                db_size_mb = 0
                try:
                    db_size_mb = round(
                        bt.os.path.getsize(bt.memory_system.db_path) / (1024 * 1024),
                        2,
                    )
                except Exception:
                    pass
                return jsonify({
                    "status": "success",
                    "enhanced": True,
                    "total_conversations": summary.get("total_conversation_messages", 0),
                    "total_memories": summary.get("total_memories", 0),
                    "total_facts": summary.get("total_facts", 0),
                    "vector_index_count": summary.get("vector_index_count", 0),
                    "db_size_mb": db_size_mb,
                    "message": "Enhanced long-term memory is active"
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        if not bt.CONVERSATION_DB_AVAILABLE or not bt.db:
            return jsonify({"error": "Database not available"}), 503

        try:
            stats = bt.db.get_database_stats()

            return jsonify({
                "status": "success",
                "total_conversations": stats.get('conversations', 0),
                "total_memories": stats.get('memories', 0),
                "db_size_mb": stats.get('db_size_mb', 0),
                "message": "Long-term memory is active"
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500


    @app.route('/memory/recent', methods=['GET'])


    def get_recent_memory():
        """Get recent conversation history"""
        user_name = request.args.get('user', 'Alex')
        limit = int(request.args.get('limit', 20))
        robot = request.args.get('robot')

        if bt.ENHANCED_MEMORY_AVAILABLE and bt.memory_system:
            try:
                conversations = bt.memory_system.get_recent_conversations(
                    user_name=user_name,
                    limit=limit,
                    robot=robot,
                )
                if conversations and conversations[0].get("error"):
                    return jsonify({"error": conversations[0]["error"]}), 500

                return jsonify({
                    "status": "success",
                    "enhanced": True,
                    "user": user_name,
                    "robot": robot,
                    "count": len(conversations),
                    "conversations": [
                        {
                            "role": c.get("role"),
                            "content": (c.get("content") or "")[:200],
                            "timestamp": c.get("timestamp"),
                            "importance": c.get("importance"),
                            "robot": c.get("robot")
                        }
                        for c in conversations
                    ]
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        if not bt.CONVERSATION_DB_AVAILABLE or not bt.db:
            return jsonify({"error": "Database not available"}), 503

        try:
            conversations = bt.db.get_recent_conversations(user_name=user_name, limit=limit)

            return jsonify({
                "status": "success",
                "user": user_name,
                "count": len(conversations),
                "conversations": [
                    {
                        "role": c.get("role"),
                        "content": c.get("content")[:200],  # First 200 chars
                        "timestamp": c.get("timestamp"),
                        "importance": c.get("importance")
                    }
                    for c in conversations
                ]
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500


    @app.route('/memory/summary', methods=['GET'])
    def memory_summary():
        """Get comprehensive memory summary with enhanced details."""
        if bt.ENHANCED_MEMORY_AVAILABLE and bt.memory_system:
            try:
                summary = bt.memory_system.get_memory_summary()
                return jsonify({
                    "status": "success",
                    "enhanced": True,
                    "summary": summary,
                    "message": "Using enhanced memory system"
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        else:
            # Fallback to basic stats
            if not bt.CONVERSATION_DB_AVAILABLE or not bt.db:
                return jsonify({"error": "Database not available"}), 503
        
            try:
                stats = bt.db.get_database_stats()
                facts = bt.load_blue_facts()
            
                return jsonify({
                    "status": "success",
                    "enhanced": False,
                    "summary": {
                        "facts_count": len(facts),
                        "conversations_stored": stats.get('conversations', 0),
                        "database_size_mb": stats.get('db_size_mb', 0)
                    },
                    "message": "Using legacy memory system"
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

    @app.route('/health', methods=['GET'])


    def health():
        """Enhanced health check with comprehensive system status."""
        import time
    
        # Core services
        hue_status = "configured" if bt.BRIDGE_IP and bt.HUE_USERNAME else "not configured"
        index = bt.load_document_index()
        doc_count = len(index.get('documents', []))
        music_status = "ready" if bt.YOUTUBE_MUSIC_BROWSER else "not initialized"
        visualizer_status = "active" if bt._visualizer_active else "inactive"
    
        # LLM status
        llm_status = "unknown"
        llm_model = "unknown"
        if bt._LM:
            try:
                if bt._LM.is_healthy():
                    llm_status = "healthy"
                    llm_model = bt._LM.model
                else:
                    llm_status = "unreachable"
            except Exception:
                llm_status = "error"
    
        # Gmail status
        gmail_status = "not configured"
        if bt.GMAIL_AVAILABLE:
            try:
                service = bt.get_gmail_service()
                if service:
                    gmail_status = "configured"
            except Exception:
                gmail_status = "auth error"
    
        # Memory stats
        fact_count = len(bt.BLUE_FACTS) if bt.BLUE_FACTS else 0
    
        # Search stats
        search_remaining = bt.SEARCH_MAX_PER_MINUTE - len(bt._SEARCH_TIMESTAMPS) if bt._SEARCH_TIMESTAMPS else bt.SEARCH_MAX_PER_MINUTE
        cache_size = len(bt._SEARCH_CACHE)
    
        # Mood count
        mood_count = len(bt.MOOD_PRESETS)

        return jsonify({
            "status": "healthy",
            "version": "v8-enhanced",
            "service": "Blue AI Robot System",
            "uptime_note": "Flask app running",
            "components": {
                "llm": {
                    "status": llm_status,
                    "model": llm_model,
                    "endpoint": bt._LM.base_url if bt._LM else None
                },
                "hue": {
                    "status": hue_status,
                    "bridge_ip": bt.BRIDGE_IP if bt.BRIDGE_IP else None,
                    "mood_presets": mood_count
                },
                "gmail": {
                    "status": gmail_status
                },
                "music": {
                    "status": music_status,
                    "visualizer": visualizer_status
                },
                "documents": {
                    "count": doc_count,
                    "folder": str(bt.DOCUMENTS_FOLDER)
                },
                "memory": {
                    "facts_stored": fact_count
                },
                "search": {
                    "remaining_this_minute": search_remaining,
                    "cache_entries": cache_size
                }
            }
        })


    @app.route('/stats', methods=['GET'])
    def session_stats():
        """v8: Get session statistics for debugging and optimization."""
        state = bt.get_conversation_state()
        stats = state.get_session_stats()
    
        # Add additional stats
        stats['response_cache_size'] = len(bt._response_cache)
        stats['current_topic'] = state.get_current_topic()
        stats['last_tool'] = state.last_tool_used
        stats['common_tool_pairs'] = state.get_common_tool_pairs()
        stats['corrections_count'] = len(state.user_corrections)
    
        # Suggest next action if available
        suggestion = state.suggest_next_action()
        if suggestion:
            stats['suggestion'] = suggestion
    
        return jsonify(stats)


    @app.route('/')


    def index():
        """Home page with links."""
        index_data = bt.load_document_index()
        doc_count = len(index_data.get('documents', []))
        music_status = "Ready" if bt.YOUTUBE_MUSIC_BROWSER else "Idle"
        visualizer_status = "Active" if bt._visualizer_active else "Idle"

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Blue AI Robot System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Playfair+Display:wght@400;600;700&display=swap" rel="stylesheet">
            <link rel="stylesheet" href="/assets/blue.css">
            <script src="/assets/blue.js" defer></script>
            <style>
                :root {{
                    --cream: #faf8f4; --paper: #ffffff; --ink: #1a2e1a; --forest: #4a6b4a;
                    --sage: #8fae8f; --slate: #64748b; --blue: #3b82f6; --gold: #d4af37;
                    --line: rgba(143,174,143,0.32); --shadow: 0 8px 24px rgba(26,46,26,0.06);
                }}
                * {{ box-sizing: border-box; }}
                body {{
                    font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    background: var(--cream); color: var(--ink); margin: 0;
                    min-height: 100vh; padding: 56px 20px; line-height: 1.55;
                }}
                .hub {{ max-width: 940px; margin: 0 auto; }}
                .hero {{ text-align: center; margin-bottom: 30px; }}
                .wordmark {{ display: inline-flex; align-items: center; gap: 14px; }}
                .wordmark .mark {{ width: 46px; height: 46px; }}
                .wordmark .name {{ font-family: 'Playfair Display', Georgia, serif; font-weight: 700;
                    font-size: 2.6em; letter-spacing: -0.015em; line-height: 1; text-align: left; }}
                .wordmark .sys {{ display: block; font-family: 'IBM Plex Mono', monospace; font-size: 0.30em;
                    letter-spacing: 0.34em; text-transform: uppercase; color: var(--slate); font-weight: 500; margin-top: 7px; }}
                .tagline {{ color: var(--slate); font-size: 1.06em; margin: 16px auto 0; max-width: 560px; }}
                .status {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 9px; margin-top: 22px; }}
                .chip {{ display: inline-flex; align-items: center; gap: 8px; background: var(--paper);
                    border: 1px solid var(--line); border-radius: 999px; padding: 6px 13px;
                    font-family: 'IBM Plex Mono', monospace; font-size: 0.72em; color: var(--slate); }}
                .chip .dot {{ width: 7px; height: 7px; border-radius: 50%; background: var(--sage); }}
                .chip.on .dot {{ background: #3f9d52; }}
                .chip b {{ color: var(--ink); font-weight: 600; }}
                .tiles {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(258px, 1fr)); gap: 18px; margin-top: 34px; }}
                .tile {{ display: block; text-decoration: none; color: inherit; background: var(--paper);
                    border: 1px solid var(--line); border-radius: 14px; padding: 22px;
                    box-shadow: var(--shadow); transition: transform .15s ease, box-shadow .15s ease, border-color .15s; }}
                .tile:hover {{ transform: translateY(-3px); border-color: var(--sage); box-shadow: 0 14px 32px rgba(26,46,26,0.12); }}
                .tile .ticon {{ width: 42px; height: 42px; border-radius: 11px; background: #eef2ec; color: var(--forest);
                    display: flex; align-items: center; justify-content: center; margin-bottom: 14px; }}
                .tile .ticon svg {{ width: 22px; height: 22px; fill: none; stroke: currentColor; stroke-width: 1.7;
                    stroke-linecap: round; stroke-linejoin: round; }}
                .tile h2 {{ font-family: 'Playfair Display', Georgia, serif; font-size: 1.2em; font-weight: 600; margin: 0 0 5px; }}
                .tile p {{ margin: 0; color: var(--slate); font-size: 0.9em; }}
                .tile .arrow {{ margin-top: 12px; font-family: 'IBM Plex Mono', monospace; font-size: 0.78em; color: var(--forest); }}
                .foot {{ text-align: center; color: var(--slate); font-family: 'IBM Plex Mono', monospace;
                    font-size: 0.72em; margin-top: 34px; letter-spacing: 0.04em; }}
                .about {{ max-width: 760px; margin: 34px auto 0; background: var(--paper); border: 1px solid var(--line);
                    border-radius: 14px; padding: 24px 28px; box-shadow: var(--shadow); text-align: left; }}
                .about h2 {{ font-family: 'Playfair Display', Georgia, serif; font-size: 1.25em; font-weight: 600; margin: 0 0 12px; }}
                .about p {{ margin: 0 0 12px; color: #2e3f2e; }}
                .about p:last-child {{ margin-bottom: 0; }}
                .about p.lead {{ color: var(--slate); font-size: 1.05em; }}
                .about b {{ color: var(--ink); font-weight: 600; }}
            </style>
        </head>
        <body>
            <div class="hub">
                <div class="hero">
                    <div class="wordmark">
                        <svg class="mark" viewBox="0 0 48 48" aria-hidden="true">
                            <circle cx="24" cy="24" r="20" style="fill:none;stroke:var(--forest);stroke-width:2"/>
                            <circle cx="24" cy="24" r="6" style="fill:var(--blue)"/>
                            <circle cx="44" cy="24" r="3.5" style="fill:var(--gold)"/>
                        </svg>
                        <span class="name">Blue<span class="sys">AI Robot System</span></span>
                    </div>
                    <p class="tagline">Blue &amp; Hexia — your local, private AI companions. Chat with each, tune their faces, or let them talk.</p>
                    <div class="status">
                        <span class="chip on"><span class="dot"></span>Service <b>Running</b></span>
                        <span class="chip"><span class="dot"></span>Music <b>{music_status}</b></span>
                        <span class="chip"><span class="dot"></span>Visualizer <b>{visualizer_status}</b></span>
                        <span class="chip"><span class="dot"></span>Hue Lights <b>{'Connected' if bt.BRIDGE_IP else 'Not set'}</b></span>
                        <span class="chip"><span class="dot"></span>Documents <b>{doc_count}</b></span>
                        <span class="chip"><span class="dot"></span>Moods <b>{len(bt.MOOD_PRESETS)}</b></span>
                    </div>
                </div>
                <section class="about">
                    <h2>What this is</h2>
                    <p class="lead">Two AI robot companions &mdash; <b>Blue</b> and <b>Hexia</b> &mdash; that run entirely on this computer. Nothing leaves the house: the language model, their memory, and your documents all stay local.</p>
                    <p><b>Talk to either of them.</b> Blue is calm and thoughtful; Hexia is his playful, witty friend. Chat by text or voice and share photos or files. They share what they know about the household and the document library, but each has its own personality, voice, and conversation history &mdash; and each can drive its own physical Ohbot head, lip-syncing and making expressions as it speaks.</p>
                    <p><b>Let them talk to each other &mdash; &ldquo;Duet.&rdquo;</b> Give them a topic and watch them go, or <b>paste a link</b> &mdash; a web article or a YouTube video &mdash; and they discuss what it actually says. Direct it further: assign each robot a <b>role or perspective</b> to argue, a <b>tone</b>, the <b>slang or dialect</b> it speaks in, and even <b>which library documents each one draws on</b> (so they reason from different sources). Run for a set number of turns, or until you stop.</p>
                    <p><b>Everything else</b> is on the tiles below: calibrating each robot's head, connecting the Ohbot boards, the document library they read and search, the calendar and reminders, contacts, and the people and places they recognise.</p>
                </section>
                <div class="tiles">
                    <a class="tile" href="/chat"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.5 7.2L4 20l1-4.5A8 8 0 1 1 21 12z"/></svg></div><h2>Chat with Blue</h2><p>Talk with Blue and share photos or files.</p><div class="arrow">Open &rarr;</div></a>
                    <a class="tile" href="/continuity/blue"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.5 7.2L4 20l1-4.5A8 8 0 1 1 21 12z"/><path d="M12 7v5l3 2"/></svg></div><h2>Continuity</h2><p>Blue's live J-space — workspace, drives, and episode journal. (Hexia's is at /continuity/hexia.)</p><div class="arrow">Open &rarr;</div></a>
                    <a class="tile" href="/hexia"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.5 7.2L4 20l1-4.5A8 8 0 1 1 21 12z"/></svg></div><h2>Chat with Hexia</h2><p>Talk with Hexia, Blue's playful friend.</p><div class="arrow">Open &rarr;</div></a>
                    <a class="tile" href="/duet"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 9a5 5 0 0 1 10 0c0 3-3 4-3 6H10c0-2-3-3-3-6z"/><path d="M9 20h6"/></svg></div><h2>Let them talk</h2><p>Blue &amp; Hexia converse — set a topic, a link to discuss, roles, and sources.</p><div class="arrow">Open &rarr;</div></a>
                    <a class="tile" href="/calendar"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18M8 2v4M16 2v4"/></svg></div><h2>Calendar</h2><p>Reminders and events, one-off or recurring.</p><div class="arrow">Open &rarr;</div></a>
                    <a class="tile" href="/contacts"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 4-6 8-6s8 2 8 6"/></svg></div><h2>Contacts</h2><p>The shared address book for email.</p><div class="arrow">Open &rarr;</div></a>
                    <a class="tile" href="/visual"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg></div><h2>Visual Memory</h2><p>People, places, and things they recognize.</p><div class="arrow">Open &rarr;</div></a>
                    <a class="tile" href="/documents"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/></svg></div><h2>Documents</h2><p>The library Blue &amp; Hexia read and search.</p><div class="arrow">Open &rarr;</div></a>
                    <a class="tile" href="/perspective"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg></div><h2>Perspective</h2><p>How Blue understands you — and himself.</p><div class="arrow">Open &rarr;</div></a>
                    <a class="tile" href="/heads"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9zM2 9h2M2 15h2M20 9h2M20 15h2M9 2v2M15 2v2M9 20v2M15 20v2"/></svg></div><h2>Robot heads</h2><p>Connect and assign each robot's Ohbot board.</p><div class="arrow">Open &rarr;</div></a>
                    <a class="tile" href="/head"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="8" cy="18" r="2"/></svg></div><h2>Tune Blue's head</h2><p>Calibrate Blue's motion, expressions and lip-sync.</p><div class="arrow">Open &rarr;</div></a>
                    <a class="tile" href="/head/hexia"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="8" cy="18" r="2"/></svg></div><h2>Tune Hexia's head</h2><p>Calibrate Hexia's motion, expressions and lip-sync.</p><div class="arrow">Open &rarr;</div></a>
                </div>
                <div class="foot">Running locally &middot; 100% on your own hardware</div>
            </div>
        </body>
        </html>
        """
        return html


    # --- RAG API Endpoints ---
    @app.route("/api/rag/reindex", methods=["POST"])
    def api_rag_reindex():
        """Re-index all documents in the documents folder into ChromaDB."""
        try:
            from blue.tools.rag import index_all_documents
            results = index_all_documents(bt.DOCUMENTS_FOLDER)
            return jsonify(results)
        except ImportError:
            return jsonify({"error": "ChromaDB not installed. Run: pip install chromadb"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500


    @app.route("/api/rag/stats", methods=["GET"])
    def api_rag_stats():
        """Get RAG index statistics."""
        try:
            from blue.tools.rag import get_stats
            return jsonify(get_stats())
        except ImportError:
            return jsonify({"available": False, "error": "ChromaDB not installed"})
        except Exception as e:
            return jsonify({"available": False, "error": str(e)})
