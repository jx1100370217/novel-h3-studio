"""Global policy: every novel-cinematic story uses dialogue-first, scene-based
screenwriting and a shot-level scene plan. These assertions are deliberately
about the shared workflow files, not about any one project.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "openmontage"
SKILLS = BASE / "skills" / "pipelines" / "novel-cinematic"
MANIFEST = BASE / "pipeline_defs" / "novel-cinematic.yaml"


def test_manifest_requires_screenplay_and_shot_splitting():
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    stages = {stage["name"]: stage for stage in manifest["stages"]}
    assert "breakdown" in stages
    assert "screenplay" in stages
    assert "scene_plan" in stages
    assert "screenplay_treatment" in stages["screenplay"]["produces"]
    assert "script" in stages["screenplay"]["produces"]
    assert "screenplay_treatment" in stages["scene_plan"]["required_artifacts_in"]
    screenplay_text = " ".join(stages["screenplay"]["review_focus"])
    assert "Dialogue carries the story" in screenplay_text
    assert "added_dialogue" in screenplay_text
    scene_text = " ".join(stages["scene_plan"]["review_focus"])
    assert "3–7" in scene_text
    assert "no 60-second single take" in scene_text


def test_screenplay_skill_is_dialogue_first_and_uncapped():
    body = (SKILLS / "screenplay-director.md").read_text(encoding="utf-8")
    assert "Dialogue-first, narration last" in body
    assert "soft estimate, not a hard cap" in body
    assert "8–14" in body
    assert "added_dialogue" in body
    assert "never write a 60-second scene as a single" in body.lower() or "never write a 60-second scene" in body.lower()


def test_scene_director_splits_scenes_into_shots():
    body = (SKILLS / "scene-director.md").read_text(encoding="utf-8")
    assert "3–7 shots (typically 3–5)" in body
    assert "No shot should be a 60-second take" in body
    assert "project-local contract" in body
    assert "screenplay_treatment" in body


def test_agents_carries_the_global_rules():
    body = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Every novel-cinematic story runs the screenplay stage" in body
    assert "Scene-based screenplay" in body
    assert "Scene plan splits into shots" in body
    assert "Dialogue-first narrative" in body
    assert "Story duration is not a hard cap" in body


def test_treatment_schema_has_dialogue_and_shot_contracts():
    schema = json.loads(
        (BASE / "schemas" / "artifacts" / "screenplay_treatment.schema.json").read_text(encoding="utf-8")
    )
    assert "added_dialogue" in schema["properties"]
    assert "shot_contracts" in schema["properties"]
    template = json.loads((SKILLS / "screenplay-treatment-template.json").read_text(encoding="utf-8"))
    assert "added_dialogue" in template


def test_audit_understands_declared_dialogue_and_narrator_warnings():
    body = (ROOT / "novel_h3" / "screenplay_audit.py").read_text(encoding="utf-8")
    assert "added_dialogue" in body
    assert "narrator_lines" in body
    assert "neither in the base script nor declared" in body
