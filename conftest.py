"""Test-suite guard: never start the live continuity workers.

Importing bluetools registers the continuity routes, and registering them used
to start one worker and one idle thread per robot. Those threads claim real
reflection jobs from data/*space/continuity.db and run them against the live
model. Pytest imports this file before any test module, so the switch is set
before bluetools is first imported.
"""

import os

os.environ.setdefault("BLUE_CONTINUITY_THREADS", "0")
