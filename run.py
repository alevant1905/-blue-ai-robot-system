#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Blue AI Robot System - Entry Point
===================================

Run with: python run.py

Loads the server (bluetools.py), reports the services it found, starts the
proactive heartbeat and serves the app.

Where the code lives:
    bluetools.py             # the server: app, auth, tools, the model loop, chat
    blue/
    ├── server/              # pages, routes and the pieces split out of bluetools
    ├── tool_selector/       # intent detection & tool selection
    ├── tools/               # library index, scholar search, page fetching, faces
    ├── head.py              # the robot heads (Blue, Hexia, Casper)
    ├── continuity.py        # each robot's J-space store
    └── llm.py, utils.py     # shared transport and helpers
    blue_memory_improved.py  # facts, memories, the conversation log
    blue_identity.py         # who is who, and the reply checks about it

The service report below reads the server's own state. It used to import a
second copy of the music, lights, Gmail and camera code from blue/tools/,
which the server never ran, so a tick here said nothing about Blue.
"""

import sys
import os
import io

# Ensure we're in the right directory
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# Add to path if needed
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)


def fix_console_encoding() -> None:
    """Windows consoles choke on the emoji below. Called from main(), not at
    import, so importing this module (the tests do) leaves stdout alone."""
    if sys.platform != 'win32':
        return
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            continue
        setattr(sys, name, io.TextIOWrapper(
            buffer,
            encoding='utf-8',
            errors='replace',
            line_buffering=True,
            write_through=True,
        ))


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
    print("🤖 Blue AI Robot System")
    print("=" * 60)


def check_modular_imports():
    """Verify the tool selector loads and can read a request."""
    print("\n📦 Checking the tool selector...")
    try:
        from blue.tool_selector import ImprovedToolSelector
        selector = ImprovedToolSelector()
        # Detection only: nothing is played.
        result = selector.select_tool("play some jazz music", [])
        if result.primary_tool:
            print(f"   ✅ Tool selector working (test: {result.primary_tool.tool_name})")
        else:
            print("   ✅ Tool selector loaded")
    except Exception as e:
        print(f"   ❌ Tool selector: {e}")
        return False
    return True


def check_services(server):
    """Report the services as the loaded server sees them."""
    print("\n🔌 Checking services...")

    # Philips Hue
    try:
        bridge = getattr(server, "BRIDGE_IP", "")
        if bridge and getattr(server, "HUE_USERNAME", ""):
            lights = server.get_hue_lights()
            if lights:
                print(f"   ✅ Philips Hue: {len(lights)} light(s) at {bridge}")
            else:
                print(f"   ⚠️  Philips Hue: no answer from the bridge at {bridge} "
                      "(off the home network?)")
        else:
            print("   ⚠️  Philips Hue: Not configured")
    except Exception as e:
        print(f"   ❌ Philips Hue: {e}")

    # YouTube Music
    try:
        if server.init_youtube_music():
            print("   ✅ YouTube Music: Ready")
        else:
            print("   ⚠️  YouTube Music: Not available (pip install ytmusicapi)")
    except Exception as e:
        print(f"   ❌ YouTube Music: {e}")

    # Gmail
    try:
        if getattr(server, "GMAIL_AVAILABLE", False):
            print("   ✅ Gmail: Available")
        else:
            print("   ⚠️  Gmail: Not configured")
    except Exception as e:
        print(f"   ❌ Gmail: {e}")

    # Documents
    try:
        index = server.load_document_index()
        doc_count = len(index.get('documents', []))
        print(f"   ✅ Documents: {doc_count} indexed")
    except Exception as e:
        print(f"   ❌ Documents: {e}")

    # The robots
    try:
        names = ", ".join(cfg["name"] for cfg in server.ROBOTS.values())
        print(f"   ✅ Robots: {names}")
    except Exception as e:
        print(f"   ❌ Robots: {e}")


def print_usage():
    print("\n" + "=" * 60)
    print("📖 Usage Examples:")
    print("   🎵 'Play Bohemian Rhapsody by Queen'")
    print("   💡 'Set the lights to sunset mood'")
    print("   📧 'Check my email'")
    print("   🔍 'Search for AI news'")
    print("   📄 'What does my contract say about...'")
    print("=" * 60)


def run_server():
    """Load the server, report its services, and serve it."""
    print("\n🚀 Starting server...")
    print("   Loading bluetools.py")
    print("")

    import bluetools

    check_services(bluetools)
    print_usage()

    # Start the proactive heartbeat (reminder emails + alert queue).
    # bluetools.py only starts this from inside its `if __name__ == "__main__":`
    # block, which we bypass by importing rather than executing, so we have
    # to kick it off explicitly here.
    try:
        import blue_proactive
        blue_proactive.start()
    except Exception as e:
        print(f"   ⚠️  Proactive heartbeat failed to start: {e}")

    # Bind to all interfaces by default so phones/laptops can reach Blue.
    # Remote requests are gated by the password (see _require_remote_auth
    # in bluetools.py); localhost stays ungated for the Ohbot client.
    # Override with BLUE_HOST=127.0.0.1 to restrict to this machine only.
    bind_host = os.environ.get("BLUE_HOST", "0.0.0.0")
    port = int(os.environ.get("BLUE_PORT", "5000"))
    print(f"\n   Server starting on http://{bind_host}:{port}")
    print("   Remote devices must sign in with the access password.")
    print("   Press CTRL+C to quit")
    print("")
    if hasattr(bluetools, 'app'):
        serve_app(bluetools.app, bind_host, port)


def main():
    """Main entry point."""
    fix_console_encoding()
    print_banner()

    if not check_modular_imports():
        print("\n❌ The tool selector failed to load!")
        print("   Please check the blue package.")
        return

    run_server()


if __name__ == "__main__":
    main()
