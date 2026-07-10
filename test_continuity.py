"""Focused tests for Blue-J's durable continuity store."""

import json

import pytest

from blue.continuity import ContinuityStore, DEFAULT_DRIVES


SEED = (
    "FOCUS: test.\n"
    "WORKING BELIEFS: persistence matters (0.5).\n"
    "OPEN QUESTIONS: none.\n"
    "COMMITMENTS: stay accurate.\n"
    "SELF-OBSERVATIONS: this is a test.\n"
    "NEXT EXPECTATION: another event."
)


def make_store(tmp_path):
    return ContinuityStore(tmp_path / "bluej", SEED)


def test_episode_persistence_and_external_deduplication(tmp_path):
    store = make_store(tmp_path)
    first = store.append_episode(
        kind="perception",
        source="visual_memory",
        summary="A lamp is on.",
        external_key="visual:1",
    )
    duplicate = store.append_episode(
        kind="perception",
        source="visual_memory",
        summary="This duplicate must not replace the first.",
        external_key="visual:1",
    )

    assert first["created"] is True
    assert duplicate["created"] is False
    assert duplicate["id"] == first["id"]

    reopened = ContinuityStore(tmp_path / "bluej", SEED)
    episodes = reopened.list_episodes()
    assert len(episodes) == 1
    assert episodes[0]["summary"] == "A lamp is on."


def test_correction_supersedes_without_rewriting_history(tmp_path):
    store = make_store(tmp_path)
    original = store.append_episode(
        kind="exchange", source="chat", summary="The appointment is Tuesday."
    )
    correction = store.correct_episode(
        original["id"], "The appointment is Wednesday.", "Alex corrected the day."
    )

    active_ids = {episode["id"] for episode in store.list_episodes()}
    audit_ids = {
        episode["id"]
        for episode in store.list_episodes(include_superseded=True)
    }
    assert original["id"] not in active_ids
    assert correction["id"] in active_ids
    assert {original["id"], correction["id"]}.issubset(audit_ids)


def test_privacy_delete_removes_the_entire_correction_chain(tmp_path):
    store = make_store(tmp_path)
    original = store.append_episode(
        kind="exchange", source="chat", summary="Private original."
    )
    correction = store.correct_episode(original["id"], "Private correction.")
    second = store.correct_episode(correction["id"], "Final private correction.")

    deletion = store.delete_episode(second["id"], "Remove the private event.")
    all_episodes = store.list_episodes(include_superseded=True)
    ids = {episode["id"] for episode in all_episodes}

    assert deletion["kind"] == "deletion"
    assert original["id"] not in ids
    assert correction["id"] not in ids
    assert second["id"] not in ids
    assert "Private" not in json.dumps(all_episodes)


def test_drives_are_known_bounded_signals(tmp_path):
    store = make_store(tmp_path)
    values = store.apply_drive_deltas({
        "curiosity": 9,
        "uncertainty": -9,
        "connection": float("inf"),
        "unknown_drive": 1,
    })

    assert set(values) == set(DEFAULT_DRIVES)
    assert values["curiosity"] == pytest.approx(DEFAULT_DRIVES["curiosity"] + 0.15)
    assert values["uncertainty"] == pytest.approx(DEFAULT_DRIVES["uncertainty"] - 0.15)
    assert values["connection"] == pytest.approx(DEFAULT_DRIVES["connection"] - 0.15)
    assert all(0.0 <= value <= 1.0 for value in values.values())


def test_reflection_jobs_are_claimed_one_at_a_time_across_instances(tmp_path):
    first_store = make_store(tmp_path)
    second_store = ContinuityStore(tmp_path / "bluej", SEED)
    first_id = first_store.enqueue_reflection("exchange", [], "first")
    second_id = first_store.enqueue_reflection("idle", [], "second")

    first_job = first_store.claim_reflection()
    assert first_job["id"] == first_id
    assert second_store.claim_reflection() is None

    first_store.finish_reflection(first_id)
    second_job = second_store.claim_reflection()
    assert second_job["id"] == second_id


def test_workspace_compare_and_set_blocks_stale_reflections(tmp_path):
    store = make_store(tmp_path)
    initial = store.get_workspace()
    updated, current = store.update_workspace(SEED.replace("test", "changed"), initial["version"])

    assert updated is True
    stale, unchanged = store.update_workspace("FOCUS: stale", initial["version"])
    assert stale is False
    assert unchanged["version"] == current["version"]
    assert "changed" in unchanged["workspace"]


def test_reflection_workspace_drives_episode_and_job_commit_atomically(tmp_path):
    store = make_store(tmp_path)
    job_id = store.enqueue_reflection("exchange", [], "commit together")
    job = store.claim_reflection()
    workspace = store.get_workspace()

    committed, revised, drives, episode = store.commit_reflection(
        job_id=job_id,
        workspace_content=SEED.replace("test", "atomic"),
        expected_version=workspace["version"],
        drive_deltas={"commitment": 0.1},
        elapsed_hours=0,
        episode_kind="reflection",
        episode_summary="The reflection committed as one unit.",
        episode_details={"job": job["id"]},
        parent_id=None,
        provenance="test",
    )

    assert committed is True
    assert revised["version"] == workspace["version"] + 1
    assert drives["commitment"] == pytest.approx(DEFAULT_DRIVES["commitment"] + 0.1)
    assert episode["details"]["workspace_version"] == revised["version"]
    assert store.pending_reflections() == 0


def test_wipe_reset_invalidates_workers_and_restores_defaults(tmp_path):
    store = make_store(tmp_path)
    episode = store.append_episode(kind="exchange", source="chat", summary="Before reset")
    before = store.get_workspace()
    store.apply_drive_deltas({"curiosity": 0.15})

    archive = store.archive_and_reset(archive=False)
    after = store.get_workspace()

    assert archive is None
    assert store.get_episode(episode["id"]) is None
    assert store.list_episodes() == []
    assert store.get_drives() == DEFAULT_DRIVES
    assert after["workspace"] == SEED
    assert after["version"] > before["version"]
    stale, _ = store.update_workspace("FOCUS: stale worker", before["version"])
    assert stale is False
