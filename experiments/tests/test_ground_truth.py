"""The declared ground truth exists, is complete, and matches the configs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from config import load_all

DATA = Path(__file__).resolve().parent.parent / "data"


def ground_truth() -> dict:
    return json.loads((DATA / "ground_truth.json").read_text(encoding="utf-8"))


def test_the_ground_truth_file_exists_and_covers_every_config() -> None:
    document = ground_truth()
    assert document["experiment"] == "greenlit-accuracy"
    declared = {app["id"]: app for app in document["apps"]}
    configs = {config.id: config for config in load_all()}
    assert set(declared) == set(configs)
    assert len(declared) == 10


def test_every_entry_is_complete_before_any_run() -> None:
    for app in ground_truth()["apps"]:
        for field in (
            "id",
            "port",
            "fault",
            "seed",
            "expected_verdict",
            "expected_reason",
            "truth_notes",
            "uncertain_truth",
        ):
            assert field in app, f"{app.get('id')} is missing {field}"
        assert app["expected_verdict"] in {"GO", "REVIEW", "NO_GO", "UNCERTAIN"}
        assert app["expected_reason"].strip()
        assert app["truth_notes"].strip()


def test_the_file_agrees_with_each_config_and_is_not_stale() -> None:
    declared = {app["id"]: app for app in ground_truth()["apps"]}
    for config in load_all():
        entry = declared[config.id]
        assert entry["expected_verdict"] == config.expected_verdict
        assert entry["expected_reason"] == config.expected_reason
        assert entry["seed"] == config.seed
        assert entry["port"] == config.port
        assert entry["uncertain_truth"] == config.uncertain_truth


def test_exactly_one_app_is_declared_uncertain() -> None:
    uncertain = [app for app in ground_truth()["apps"] if app["uncertain_truth"]]
    assert [app["id"] for app in uncertain] == ["app02"]


def test_the_declared_verdicts_are_the_ones_the_analysis_expects() -> None:
    declared = {app["id"]: app["expected_verdict"] for app in ground_truth()["apps"]}
    assert declared == {
        "app01": "GO",
        "app02": "UNCERTAIN",
        "app03": "NO_GO",
        "app04": "NO_GO",
        "app05": "NO_GO",
        "app06": "REVIEW",
        "app07": "NO_GO",
        "app08": "GO",
        "app09": "REVIEW",
        "app10": "NO_GO",
    }


def test_no_declaration_was_made_after_a_result() -> None:
    document = ground_truth()
    assert "before any GreenLit run" in document["declared"]
    with pytest.raises(KeyError):
        document["apps"][0]["observed_verdict"]
