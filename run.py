#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Blue AI Robot System - Modular Entry Point
============================================

This is the new entry point that uses the refactored modular components.
Run with: python run.py

The original bluetools.py is kept as a backup.

Module Structure:
    blue/
    ├── __init__.py          # Core exports
    ├── utils.py             # Utility functions
    ├── memory.py            # Memory/facts system
    ├── llm.py               # LLM client
    ├── tool_selector.py     # Intent detection & tool selection
    └── tools/
        ├── music.py         # YouTube Music
        ├── vision.py        # Camera & visualizer
        ├── documents.py     # Document management
        ├── lights.py        # Philips Hue
        ├── web.py           # Web search & browsing
        └── gmail.py         # Email operations
"""

import sys
import os
import io

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding='utf-8',
        errors='replace',
        line_buffering=True,
        write_through=True,
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer,
        encoding='utf-8',
        errors='replace',
        line_buffering=True,
        write_through=True,
    )

# Ensure we're in the right directory
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# Add to path if needed
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)


def serve_app(app, host: str, port: int) -> None:
    """Serve the Flask app with Waitress when available."""
    try:
        from waitress import serve
    except ImportError:
        print("   Waitress is not installed; using Flask's local/LAN development server.")
        app.run(host=host, port=port, debug=False, threaded=True)
        return

    print("   Serving with Waitress")
    serve(app, host=host, port=port, threads=8)


def print_banner():
    """Print startup banner."""
    print("=" * 60)
    print("🤖 Blue AI Robot System - MODULAR VERSION")
    print("=" * 60)

def check_modular_imports():
    """Verify modular components are available."""
    print("\n📦 Checking modular components...")

    try:
        from blue import (
            ImprovedToolSelector, ToolIntent, ToolSelectionResult,
            load_blue_facts, build_system_preamble,
            LMStudioClient, settings
        )
        print("   ✅ blue package (core)")
    except ImportError as e:
        print(f"   ❌ blue package: {e}")
        return False

    try:
        from blue.tools import (
            # Music
            init_youtube_music, play_music, control_music,
            # Lights
            get_hue_lights, apply_mood_to_lights, MOOD_PRESETS,
            # Documents
            load_document_index, search_documents_rag,
            # Web
            execute_web_search, get_weather_data,
            # Gmail
            GMAIL_AVAILABLE, execute_read_gmail,
            # Vision
            capture_camera_image, get_vision_queue,
        )
        print("   ✅ blue.tools package")
    except ImportError as e:
        print(f"   ❌ blue.tools package: {e}")
        return False

    try:
        from blue.tool_selector import ImprovedToolSelector
        selector = ImprovedToolSelector()
        # Quick test
        result = selector.select_tool("play some jazz music", [])
        if result.primary_tool:
            print(f"   ✅ Tool selector working (test: {result.primary_tool.tool_name})")
        else:
            print("   ✅ Tool selector loaded")
    except Exception as e:
        print(f"   ⚠️  Tool selector: {e}")

    return True

def check_services():
    """Check external service availability."""
    print("\n🔌 Checking services...")

    # Check Hue
    try:
        from blue.tools.lights import BRIDGE_IP, HUE_USERNAME, get_hue_lights
        if BRIDGE_IP and HUE_USERNAME:
            lights = get_hue_lights()
            if lights:
                print(f"   ✅ Philips Hue: {len(lights)} light(s) at {BRIDGE_IP}")
            else:
                print(f"   ⚠️  Philips Hue: Configured but no lights found")
        else:
            print("   ⚠️  Philips Hue: Not configured")
    except Exception as e:
        print(f"   ❌ Philips Hue: {e}")

    # Check YouTube Music
    try:
        from blue.tools.music import init_youtube_music
        if init_youtube_music():
            print("   ✅ YouTube Music: Ready")
        else:
            print("   ⚠️  YouTube Music: Not available (pip install ytmusicapi)")
    except Exception as e:
        print(f"   ❌ YouTube Music: {e}")

    # Check Gmail
    try:
        from blue.tools.gmail import GMAIL_AVAILABLE
        if GMAIL_AVAILABLE:
            print("   ✅ Gmail: Available")
        else:
            print("   ⚠️  Gmail: Not configured")
    except Exception as e:
        print(f"   ❌ Gmail: {e}")

    # Check Documents
    try:
        from blue.tools.documents import load_document_index
        index = load_document_index()
        doc_count = len(index.get('documents', []))
        print(f"   ✅ Documents: {doc_count} indexed")
    except Exception as e:
        print(f"   ❌ Documents: {e}")

def run_server():
    """Start the Flask server."""
    print("\n🚀 Starting server...")
    print("   Loading bluetools.py (this will start the Flask server)")
    print("")

    # Import bluetools and run its main function
    import bluetools

    # Start the proactive heartbeat (reminder emails + alert queue).
    # bluetools.py only starts this from inside its `if __name__ == "__main__":`
    # block, which we bypass by importing rather than executing, so we have
    # to kick it off explicitly here.
    try:
        import blue_proactive
        blue_proactive.start()
    except Exception as e:
        print(f"   ⚠️  Proactive heartbeat failed to start: {e}")

    # Run the server if bluetools has a main guard
    if hasattr(bluetools, '__name__'):
        # Bind to all interfaces by default so phones/laptops can reach Blue.
        # Remote requests are gated by the password (see _require_remote_auth
        # in bluetools.py); localhost stays ungated for the Ohbot client.
        # Override with BLUE_HOST=127.0.0.1 to restrict to this machine only.
        bind_host = os.environ.get("BLUE_HOST", "0.0.0.0")
        port = int(os.environ.get("BLUE_PORT", "5000"))
        print(f"   Server starting on http://{bind_host}:{port}")
        print("   Remote devices must sign in with the access password.")
        print("   Press CTRL+C to quit")
        print("")
        # bluetools.py is imported here, so start the server explicitly.
        if hasattr(bluetools, 'app'):
            serve_app(bluetools.app, bind_host, port)

def main():
    """Main entry point."""
    print_banner()

    # Check modular components first
    if not check_modular_imports():
        print("\n❌ Modular components failed to load!")
        print("   Please check your blue package installation.")
        return

    # Check services
    check_services()

    # Print usage info
    print("\n" + "=" * 60)
    print("📖 Usage Examples:")
    print("   🎵 'Play Bohemian Rhapsody by Queen'")
    print("   💡 'Set the lights to sunset mood'")
    print("   📧 'Check my email'")
    print("   🔍 'Search for AI news'")
    print("   📄 'What does my contract say about...'")
    print("=" * 60)

    # Start the server
    run_server()

if __name__ == "__main__":
    main()
