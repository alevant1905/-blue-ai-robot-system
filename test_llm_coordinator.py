"""The priority gate around the single local model.

Chat used to bypass the gate entirely, so the continuity reflection that fires
after every exchange competed with the user's next question for one model
(+0.40s measured). The gate is now taken at the HTTP call itself, which means
it nests inside the route-level wrappers duet, banter, panel and continuity
already use -- so re-entrancy is load-bearing, not a nicety.
"""

import threading
import time

import pytest

import blue.llm_coordinator as coordinator
from blue.llm_coordinator import llm_slot, seconds_since_foreground


def test_nested_acquire_does_not_deadlock():
    """Panel wraps a whole turn; the HTTP call inside acquires again."""
    with llm_slot(foreground=True):
        with llm_slot(foreground=True):
            with llm_slot(foreground=False):
                pass


def test_slot_is_released_after_nesting():
    """A nested exit must not free the slot the outer caller still holds."""
    order = []

    def other():
        with llm_slot(foreground=True):
            order.append("second")

    with llm_slot(foreground=True):
        with llm_slot(foreground=True):
            pass
        # The inner block exited; the slot must still be ours.
        t = threading.Thread(target=other)
        t.start()
        t.join(timeout=0.3)
        assert order == [], "another thread entered while the slot was held"
        order.append("first")
    t.join(timeout=2)
    assert order == ["first", "second"]


def test_slot_is_released_when_the_body_raises():
    with pytest.raises(ValueError):
        with llm_slot(foreground=True):
            raise ValueError("boom")
    done = []

    def other():
        with llm_slot(foreground=True):
            done.append(True)

    t = threading.Thread(target=other)
    t.start()
    t.join(timeout=2)
    assert done == [True], "the slot was never released"


def test_calls_are_serialized():
    """Two callers must not be inside the gate at the same time."""
    concurrent = []
    active = {"n": 0}
    lock = threading.Lock()

    def worker():
        with llm_slot(foreground=True):
            with lock:
                active["n"] += 1
                concurrent.append(active["n"])
            time.sleep(0.05)
            with lock:
                active["n"] -= 1

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert max(concurrent) == 1, f"{max(concurrent)} calls ran at once"


def test_a_waiting_foreground_call_goes_before_new_background_work():
    """The whole point: the user's question beats a reflection."""
    finished = []
    holder_in = threading.Event()
    release = threading.Event()

    def holder():                      # occupies the slot
        with llm_slot(foreground=False):
            holder_in.set()
            release.wait(timeout=2)

    def foreground():
        with llm_slot(foreground=True):
            finished.append("foreground")

    def background():
        with llm_slot(foreground=False):
            finished.append("background")

    h = threading.Thread(target=holder)
    h.start()
    assert holder_in.wait(timeout=2)

    f = threading.Thread(target=foreground)
    f.start()
    time.sleep(0.05)                   # let the foreground call queue up
    b = threading.Thread(target=background)
    b.start()
    time.sleep(0.05)

    release.set()
    for t in (h, f, b):
        t.join(timeout=5)

    assert finished[0] == "foreground", f"background went first: {finished}"


def test_a_nested_call_cannot_promote_background_to_foreground():
    """A reflection calling a foreground-defaulting helper stays background."""
    finished = []
    holder_in = threading.Event()
    release = threading.Event()

    def holder():
        with llm_slot(foreground=False):
            holder_in.set()
            release.wait(timeout=2)

    def reflection():
        # Declares background, then reaches a helper that asks for foreground.
        with llm_slot(foreground=False):
            with llm_slot(foreground=True):
                finished.append("reflection")

    def question():
        with llm_slot(foreground=True):
            finished.append("question")

    h = threading.Thread(target=holder)
    h.start()
    assert holder_in.wait(timeout=2)

    r = threading.Thread(target=reflection)
    r.start()
    time.sleep(0.05)
    q = threading.Thread(target=question)
    q.start()
    time.sleep(0.05)

    release.set()
    for t in (h, r, q):
        t.join(timeout=5)

    assert finished[0] == "question", (
        f"the reflection promoted itself past the live question: {finished}"
    )


def test_foreground_use_is_recorded_for_the_quiet_check():
    """Background work reads this to decide whether anyone is talking."""
    with llm_slot(foreground=True):
        pass
    assert seconds_since_foreground() < 1.0

    before = coordinator._LAST_FOREGROUND_AT
    with llm_slot(foreground=False):
        pass
    assert coordinator._LAST_FOREGROUND_AT == before, (
        "background work marked itself as a live conversation"
    )


def test_a_turn_still_waiting_for_the_model_counts_as_live():
    """The mark goes down on entry, not only on exit.

    A question queued behind something else is exactly when a reflection must
    not start — if the mark only landed on completion, the worker would see a
    quiet system and grab the model out from under a waiting user.
    """
    coordinator._LAST_FOREGROUND_AT = 0.0
    seen = []
    started = threading.Event()

    def slow_turn():
        with llm_slot(foreground=True):
            started.set()
            time.sleep(0.3)

    t = threading.Thread(target=slow_turn)
    t.start()
    assert started.wait(timeout=2)
    seen.append(seconds_since_foreground())
    t.join(timeout=5)

    assert seen[0] < 1.0, "a turn holding the model did not read as live"


def test_reflections_defer_while_a_conversation_is_live():
    """The guard the continuity worker consults before claiming a job."""
    import bluetools  # noqa: F401  -- load order: continuity imports it back
    from blue.server.routes import continuity

    coordinator._LAST_FOREGROUND_AT = 0.0
    assert not continuity._conversation_is_live(), (
        "an idle system looked busy"
    )

    with llm_slot(foreground=True):
        pass
    assert continuity._conversation_is_live(), (
        "a reflection would start while someone is mid-conversation"
    )


def test_the_quiet_window_can_be_switched_off(monkeypatch):
    import bluetools  # noqa: F401  -- load order: continuity imports it back
    from blue.server.routes import continuity

    with llm_slot(foreground=True):
        pass
    monkeypatch.setattr(continuity, "_CONVERSATION_QUIET_SECONDS", 0.0)
    assert not continuity._conversation_is_live()
