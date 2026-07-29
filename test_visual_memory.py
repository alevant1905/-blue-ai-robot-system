"""Regression tests for visual profiles, recognition, and robot provenance."""

from blue_visual_memory import VisualMemory


def test_profile_updates_preserve_reference_photo_and_do_not_fake_a_sighting(tmp_path):
    vm = VisualMemory(str(tmp_path / "visual.db"))
    assert vm.add_person("Alex", typical_appearance="beard and glasses")
    original = vm.get_person("Alex")
    photo = tmp_path / "alex.jpg"
    photo.write_bytes(b"reference")
    assert vm.set_entity_image("person", original["id"], str(photo))["success"]

    assert vm.add_person("Alex", description="Alex's updated profile")
    updated = vm.get_person("Alex")

    assert updated["id"] == original["id"]
    assert updated["image_path"] == str(photo)
    assert updated["typical_appearance"] == "beard and glasses"
    assert updated["description"] == "Alex's updated profile"
    assert updated["last_seen"] is None
    assert updated["times_seen"] == 0


def test_alias_reference_is_merged_into_one_canonical_face_identity(tmp_path):
    vm = VisualMemory(str(tmp_path / "visual.db"))
    vm.add_person("Alex", relationship="creator")
    vm.add_person("Alex (Doctor Levant)", typical_appearance="beard and glasses")
    alias = next(
        row for row in vm.get_all_people()
        if row["name"] == "Alex (Doctor Levant)"
    )
    photo = tmp_path / "alex-alias.jpg"
    photo.write_bytes(b"reference")
    vm.set_entity_image("person", alias["id"], str(photo))

    gallery = vm.get_recognition_people()
    alex_rows = [row for row in gallery if row["name"] == "Alex"]

    assert vm.resolve_person_name("Doctor Levant") == "Alex"
    assert vm.resolve_person_name("Alex (Doctor Levant)") == "Alex"
    assert len(alex_rows) == 1
    assert alex_rows[0]["image_path"] == str(photo)
    assert alex_rows[0]["typical_appearance"] == "beard and glasses"


def test_observations_and_recognition_history_are_robot_specific(tmp_path):
    vm = VisualMemory(str(tmp_path / "visual.db"))
    vm.add_person("Alex", typical_appearance="beard and glasses")
    person = vm.get_person("Alex")
    photo = tmp_path / "alex.jpg"
    photo.write_bytes(b"reference")
    vm.set_entity_image("person", person["id"], str(photo))

    blue_id = vm.log_observation(
        "Alex is wearing a grey shirt in the office.",
        people_present=["Alex (Doctor Levant)"],
        observer="blue",
        recognition=[{"name": "Alex", "confidence": 0.82,
                      "method": "opencv_sface"}],
    )
    vm.update_seen(
        "person", "Alex (Doctor Levant)", observer="blue",
        confidence=0.82, observation_id=blue_id,
    )
    vm.log_observation(
        "Hexia sees an empty room.", observer="hexia")

    blue_rows = vm.get_recent_observations(observer="blue")
    hexia_rows = vm.get_recent_observations(observer="hexia")

    assert [row["id"] for row in blue_rows] == [blue_id]
    assert blue_rows[0]["people_present"] == '["Alex"]'
    assert blue_rows[0]["recognition_json"]
    assert len(hexia_rows) == 1
    assert vm.get_person_sighting("Alex", "blue")["times_seen"] == 1
    assert vm.get_person_sighting("Alex", "hexia") is None

    blue_context = vm.get_people_memory_context("blue")
    hexia_context = vm.get_people_memory_context("hexia")
    assert "visual reference stored" in blue_context
    assert "latest visual description: Alex is wearing a grey shirt" in blue_context
    assert "you have no robot-specific sighting recorded yet" in hexia_context


def test_update_seen_uses_people_table_not_nonexistent_persons_table(tmp_path):
    vm = VisualMemory(str(tmp_path / "visual.db"))
    vm.add_person("Emmy")

    assert vm.update_seen("person", "Emmy", observer="hexia")
    assert vm.get_person("Emmy")["times_seen"] == 1
    assert vm.get_person_sighting("Emmy", "hexia")["times_seen"] == 1
