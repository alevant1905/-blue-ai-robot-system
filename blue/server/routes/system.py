"""System routes extracted verbatim from bluetools.py: home page (/),
/health, /stats, /memory/*, /api/rag/* and the shared theme assets.

All shared state stays in bluetools and is read via bt.<name> at
request time.
"""
import bluetools as bt
from blue.server.pages.system import INDEX_HTML
from flask import render_template_string, Response, jsonify, request

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
        return render_template_string(
            INDEX_HTML,
            music_status="Ready" if bt.YOUTUBE_MUSIC_BROWSER else "Idle",
            visualizer_status="Active" if bt._visualizer_active else "Idle",
            hue_status="Connected" if bt.BRIDGE_IP else "Not set",
            doc_count=len(index_data.get('documents', [])),
            mood_count=len(bt.MOOD_PRESETS),
        )


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
