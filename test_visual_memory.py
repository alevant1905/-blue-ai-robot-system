"""Regression tests for visual profiles, recognition, and robot provenance."""

import pytest

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


# ---- a look is not an outfit (2026-09-23 / 10-05) ---------------------------------
# remember_person kept Clover's "bread-bun hat and strawberry-patterned skirt"
# as her appearance; printed as her "appearance profile" beside a camera
# caption, it named whoever wore that outfit "Clover".

CLOVER_LOOK = ("TA wearing a playful food-themed costume, specifically a "
               "bread-bun hat and strawberry-patterned skirt.")


def test_the_people_block_prints_no_stored_look(tmp_path):
    vm = VisualMemory(str(tmp_path / "visual.db"))
    vm.add_person("Clover", typical_appearance=CLOVER_LOOK, relationship="TA for CS101")
    vm.add_person("Emmy", typical_appearance="long brown hair with bangs.")
    context = vm.get_people_memory_context("blue")
    assert "appearance profile" not in context
    assert "bread-bun" not in context and "long brown hair" not in context
    assert "- Clover: TA for CS101; no face reference enrolled" in context


def test_a_person_with_only_a_description_gets_no_appearance_profile(tmp_path):
    """typical_appearance or description was printed as the profile: Athena's
    read "appearance profile: her birthday is August 15"."""
    vm = VisualMemory(str(tmp_path / "visual.db"))
    vm.add_person("Athena", description="her birthday is August 15",
                  relationship="Alex's daughter")
    assert "birthday" not in vm.get_people_memory_context("blue")


def test_recognition_context_leaves_the_look_out_when_faces_are_matched(tmp_path):
    vm = VisualMemory(str(tmp_path / "visual.db"))
    vm.add_person("Clover", typical_appearance=CLOVER_LOOK, relationship="TA for CS101")
    vm.add_person("Emmy", typical_appearance="long brown hair, wearing a red hoodie")
    without = vm.get_recognition_context(include_appearance=False)
    assert "Appearance:" not in without and "Clover" in without
    # Without a face engine the look stays, but never what they had on.
    with_look = vm.get_recognition_context()
    assert "- Appearance: long brown hair" in with_look
    assert "hoodie" not in with_look and "bread-bun" not in with_look


def test_has_face_reference_needs_a_photo_on_disk(tmp_path):
    vm = VisualMemory(str(tmp_path / "visual.db"))
    vm.add_person("Clover", relationship="TA for CS101")
    vm.add_person("Felix")
    photo = tmp_path / "felix.jpg"
    photo.write_bytes(b"reference")
    vm.set_entity_image("person", vm.get_person("Felix")["id"], str(photo))
    assert not vm.has_face_reference("Clover")
    assert vm.has_face_reference("felix")
    assert not vm.has_face_reference("Nobody")
    # The live row is "Alex (Doctor Levant)"; Alex is that person.
    vm.add_person("Alex (Doctor Levant)")
    vm.set_entity_image("person", vm.get_person("Alex (Doctor Levant)")["id"], str(photo))
    assert vm.has_face_reference("Alex")


@pytest.mark.parametrize("text, kept", [
    ("long brown hair, wearing a red hoodie", "long brown hair"),
    ("bread-bun hat and strawberry skirt", ""),
    (CLOVER_LOOK, ""),
    ("man with beard and glasses", "man with beard and glasses"),
    ("salt and pepper hair", "salt and pepper hair"),
    # A stored correction about Felix: glasses are worn and still a feature.
    ("does not wear glasses", "does not wear glasses"),
    ("wears a hat and glasses", "glasses"),
    ("girl with long hair wearing a hoodie", "girl with long hair"),
    ("man with curly hair, glasses, beard, and a mustache, wearing a dark "
     "jacket; stands next to dual monitors showing code",
     "man with curly hair, glasses, beard, and a mustache"),
    # No clothes at all: a pet's look stays whole.
    ("black dog", "black dog"),
])
def test_lasting_appearance_keeps_features_not_clothes(text, kept):
    from blue_visual_memory import lasting_appearance
    assert lasting_appearance(text)[0] == kept


def test_a_look_fact_must_name_a_feature():
    """10-05: "remember what she looks like" → remember_fact clover_appearance
    = "TA for CS101; playful food-themed outfit — bread-bun hat and
    strawberry-patterned skirt, sitting in office chair…"."""
    from blue_visual_memory import is_look_fact_key, look_fact_value
    assert is_look_fact_key("clover_appearance")
    assert is_look_fact_key("what_she_looks_like")
    assert not is_look_fact_key("emmy_dance_outfit")
    assert not is_look_fact_key("alex_facebook")
    assert look_fact_value(
        "TA for CS101; playful food-themed outfit — bread-bun hat and "
        "strawberry-patterned skirt, sitting in office chair by white brick "
        "wall and bookshelf") == ""
    assert look_fact_value("TA for CS101") == ""
    assert look_fact_value("long brown hair with bangs") == "long brown hair with bangs"
