#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Laurier Library Setup for Blue
==============================
One command sets up Blue's access to full-text journal articles through
the Wilfrid Laurier University library:

    python setup_library.py

It asks for your Laurier sign-in, writes wlu_credentials.json next to
this script (the file is gitignored — it never leaves this machine),
and immediately tests the login against the library proxy so you know
it works before you ever ask Blue for a paper.

Run it again any time to update or replace the stored sign-in.
"""

import getpass
import io
import json
import os
import sys

# Windows consoles choke on the banner emoji without this (same fix as run.py).
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CRED_FILE = os.path.join(BASE_DIR, "wlu_credentials.json")


def _write_credentials(creds: dict):
    with open(CRED_FILE, "w", encoding="utf-8") as f:
        json.dump(creds, f, indent=2)
    try:
        os.chmod(CRED_FILE, 0o600)  # owner-only on Mac/Linux; harmless on Windows
    except Exception:
        pass
    print(f"\n✅ Saved to {CRED_FILE}")
    print("   (gitignored — your sign-in stays on this computer)")


def _test_login() -> bool:
    print("\n🔌 Testing the sign-in against the Laurier library proxy...")
    try:
        sys.path.insert(0, BASE_DIR)
        from blue.tools.scholar import (
            _new_proxy_session, LibraryAuthError, _auth_guidance,
        )
    except ImportError as e:
        print(f"   ⚠️  Couldn't load Blue's scholar module to test ({e}).")
        print("      The credentials are saved; Blue will use them on the next request.")
        return True
    try:
        session = _new_proxy_session()
        if any(c.name.lower().startswith("ezproxy") for c in session.cookies):
            print("   ✅ Signed in! Blue can now fetch licensed articles.")
            return True
        # Cookie mode returns a session without a round-trip; that's fine.
        print("   ✅ Credentials loaded. Blue will use them on the next article fetch.")
        return True
    except LibraryAuthError as e:
        print(f"   ❌ Sign-in did not work ({e.code}).")
        print()
        for line in _auth_guidance(e.code).split(". "):
            if line.strip():
                print(f"      {line.strip().rstrip('.')}.")
        return False
    except Exception as e:
        print(f"   ⚠️  Couldn't reach the library proxy ({e.__class__.__name__}: {e}).")
        print("      Check your internet connection; the credentials are saved and")
        print("      Blue will try them on the next article fetch.")
        return True


def main():
    print("=" * 62)
    print("🎓 Blue × Laurier Library — full-text access setup")
    print("=" * 62)
    print("""
Blue searches journals without any sign-in. Your library sign-in is
only used to fetch the FULL TEXT of licensed articles, one at a time,
exactly like clicking a library link yourself.

How would you like to sign in?

  1) Laurier username + password   (try this first)
  2) Browser session cookie        (use this if option 1 fails
                                    because of Duo / single-sign-on)
  3) Quit without changing anything
""")
    if os.path.exists(CRED_FILE):
        print(f"⚠️  {os.path.basename(CRED_FILE)} already exists — continuing will replace it.\n")

    choice = input("Pick 1, 2 or 3 and press Enter: ").strip()

    if choice == "1":
        print("\nYour Laurier username (the one for the library / MyLaurier):")
        user = input("  Username: ").strip()
        print("Your password (typing is hidden — nothing shows as you type):")
        password = getpass.getpass("  Password: ")
        if not user or not password:
            print("\n❌ Username and password can't be empty. Nothing was saved.")
            return 1
        _write_credentials({"user": user, "pass": password})
        ok = _test_login()
        if not ok:
            print("\nTip: run this script again and pick option 2 (cookie) —")
            print("it works even when the login goes through Duo.")
            return 1

    elif choice == "2":
        print("""
To get the cookie (takes ~1 minute):

  1. In your web browser, go to:  https://libproxy.wlu.ca/login
     and sign in the way you normally would (including Duo).
  2. Press F12 to open Developer Tools.
  3. Find cookies:
       Chrome/Edge:  Application tab  →  Cookies  →  libproxy.wlu.ca
       Firefox:      Storage tab      →  Cookies  →  libproxy.wlu.ca
  4. Click the cookie named  ezproxy  and copy its Value.
""")
        cookie = input("Paste the ezproxy cookie value here: ").strip()
        if not cookie:
            print("\n❌ Nothing pasted. Nothing was saved.")
            return 1
        _write_credentials({"cookie": cookie})
        _test_login()
        print("\nNote: library sessions expire after a while. If article fetches")
        print("stop working weeks from now, just run this script again.")

    else:
        print("\nNo changes made.")
        return 0

    print("\n" + "=" * 62)
    print("🎉 Done! Restart Blue (python run.py), then try something like:")
    print('   "Blue, find peer-reviewed articles on activity theory')
    print('    and read the most-cited one."')
    print("=" * 62)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\n\nCancelled — nothing was saved.")
        sys.exit(1)
