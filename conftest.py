"""Test-suite guard: never start the live background workers.

Importing bluetools registers the continuity routes and starts the email
auto-reply loop at module load. Without these switches, a test run starts
workers that claim real reflection jobs from data/*space/continuity.db and
run them on the live model, and — in any run longer than a minute — a real
sweep of Blue's Gmail inbox that can send replies. Pytest imports this file
before any test module, so the switches are set before bluetools loads.
"""

import os

os.environ.setdefault("BLUE_CONTINUITY_THREADS", "0")
os.environ.setdefault("BLUE_EMAIL_AUTOREPLY_DISABLED", "1")
