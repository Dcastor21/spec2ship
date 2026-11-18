"""Spec model and spec gate (T1.3): one valid spec, then every rejection reason."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from factory.spec import GENERIC_HINT, Spec, SpecError, lint_path, load_spec

REMOVE = object()


def valid_spec() -> dict[str, Any]:
    return {
        "id": "GO-001",
        "title": "Report missed tour checkpoints",
        "goal": "Supervisors can see which checkpoints a finished tour skipped.",
        "acceptance_criteria": ["GET /tours/{id}/missed lists checkpoints never scanned"],
        "allowed_paths": ["target/guard_ops/routes/tours.py", "target/tests/**"],
        "risk": "low",
        "budget": {"max_attempts": 3, "max_usd": 0.5},
    }


def changed(**changes: Any) -> dict[str, Any]:
    spec = valid_spec()
    for key, value in changes.items():
        if value is REMOVE:
            del spec[key]
        else:
            spec[key] = value
    return spec


def write(directory: Path, data: Any, name: str = "GO-001.yaml") -> Path:
    path = directory / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


# --- the valid case ---------------------------------------------------------


def test_valid_spec_loads(tmp_path: Path) -> None:
    spec = load_spec(write(tmp_path, valid_spec()))
    assert isinstance(spec, Spec)
    assert spec.id == "GO-001"
    assert spec.allowed_paths == ["target/guard_ops/routes/tours.py", "target/tests/**"]
    assert spec.budget.max_attempts == 3
    assert spec.budget.max_usd == 0.5


def test_valid_directory_passes_the_gate(tmp_path: Path) -> None:
    write(tmp_path, valid_spec())
    write(tmp_path, changed(id="GO-002"), "GO-002.yaml")
    report = lint_path(tmp_path)
    assert report.problems == []
    assert [spec.id for spec in report.specs] == ["GO-001", "GO-002"]


def test_budget_defaults(tmp_path: Path) -> None:
    spec = load_spec(write(tmp_path, changed(budget=REMOVE)))
    assert (spec.budget.max_attempts, spec.budget.max_usd) == (3, 1.0)


# --- one rejection per field rule -------------------------------------------

FIELD_REJECTIONS = [
    # (case, changes, where, message fragment, hint fragment)
    ("missing-id", {"id": REMOVE}, "id", "field required", "add an `id:`"),
    ("bad-id", {"id": "go-1"}, "id", "should match pattern", "like GO-001"),
    ("blank-title", {"title": "   "}, "title", "at least 1 character", "non-empty"),
    ("long-title", {"title": "x" * 81}, "title", "at most 80 characters", "at most 80"),
    ("missing-goal", {"goal": REMOVE}, "goal", "field required", "add a `goal:`"),
    (
        "no-criteria",
        {"acceptance_criteria": []},
        "acceptance_criteria",
        "at least 1 item",
        "at least one",
    ),
    (
        "blank-criterion",
        {"acceptance_criteria": [" "]},
        "acceptance_criteria[0]",
        "at least 1 character",
        "non-empty",
    ),
    (
        "criteria-not-list",
        {"acceptance_criteria": "one line"},
        "acceptance_criteria",
        "valid list",
        "YAML list",
    ),
    ("no-paths", {"allowed_paths": []}, "allowed_paths", "at least 1 item", "at least one"),
    (
        "absolute-path",
        {"allowed_paths": ["/etc/passwd"]},
        "allowed_paths[0]",
        "absolute",
        "relative to the repo root",
    ),
    (
        "drive-path",
        {"allowed_paths": ["C:/repo/target/x.py"]},
        "allowed_paths[0]",
        "absolute",
        "relative to the repo root",
    ),
    (
        "backslash-path",
        {"allowed_paths": ["target\\guard_ops\\db.py"]},
        "allowed_paths[0]",
        "backslash",
        "forward slashes",
    ),
    (
        "parent-path",
        {"allowed_paths": ["target/../pyproject.toml"]},
        "allowed_paths[0]",
        "'..'",
        "without '..'",
    ),
    (
        "outside-target",
        {"allowed_paths": ["pyproject.toml"]},
        "allowed_paths[0]",
        "inside target/",
        "under target/",
    ),
    (
        "acceptance-path",
        {"allowed_paths": ["acceptance/GO-001/test_x.py"]},
        "allowed_paths[0]",
        "inside target/",
        "under target/",
    ),
    ("bad-risk", {"risk": "medium"}, "risk", "'low' or 'high'", "use 'low' or 'high'"),
    (
        "too-many-attempts",
        {"budget": {"max_attempts": 6}},
        "budget.max_attempts",
        "less than or equal to 5",
        "at most 5",
    ),
    (
        "zero-attempts",
        {"budget": {"max_attempts": 0}},
        "budget.max_attempts",
        "greater than or equal to 1",
        "at least 1",
    ),
    ("free-run", {"budget": {"max_usd": 0}}, "budget.max_usd", "greater than 0", "above 0"),
    (
        "huge-budget",
        {"budget": {"max_usd": 50}},
        "budget.max_usd",
        "less than or equal to 5",
        "at most 5",
    ),
    (
        "unknown-field",
        {"allowed_path": ["target/x.py"]},
        "allowed_path",
        "extra inputs",
        "did you mean `allowed_paths`",
    ),
    (
        "unknown-budget-field",
        {"budget": {"max_attempt": 2}},
        "budget.max_attempt",
        "extra inputs",
        "did you mean `max_attempts`",
    ),
    # paths must be narrow, plain, and never gate configuration
    (
        "dot-prefix",
        {"allowed_paths": ["./target/x.py"]},
        "allowed_paths[0]",
        "starts with './'",
        "drop the leading './'",
    ),
    (
        "whole-target",
        {"allowed_paths": ["target/"]},
        "allowed_paths[0]",
        "all of target/",
        "name the files",
    ),
    (
        "whole-target-glob",
        {"allowed_paths": ["target/**"]},
        "allowed_paths[0]",
        "all of target/",
        "name the files",
    ),
    (
        "conftest",
        {"allowed_paths": ["target/tests/conftest.py"]},
        "allowed_paths[0]",
        "configures the gates",
        "only a human edits it",
    ),
    (
        "control-char",
        {"allowed_paths": ["target/x\n.py"]},
        "allowed_paths[0]",
        "control characters or braces",
        "plain path",
    ),
    (
        "brace-glob",
        {"allowed_paths": ["target/{a,..}/b.py"]},
        "allowed_paths[0]",
        "control characters or braces",
        "plain path",
    ),
    # wrong types
    ("budget-not-mapping", {"budget": 5}, "budget", "valid dictionary", "YAML mapping"),
    ("title-not-text", {"title": 123}, "title", "valid string", "plain text"),
    (
        "bool-attempts",
        {"budget": {"max_attempts": True}},
        "budget.max_attempts",
        "true/false",
        "not true/false",
    ),
    ("bool-usd", {"budget": {"max_usd": True}}, "budget.max_usd", "true/false", "not true/false"),
    (
        "word-attempts",
        {"budget": {"max_attempts": "three"}},
        "budget.max_attempts",
        "valid integer",
        "whole number",
    ),
    (
        "fraction-attempts",
        {"budget": {"max_attempts": 2.5}},
        "budget.max_attempts",
        "fractional part",
        "whole number",
    ),
    (
        "list-attempts",
        {"budget": {"max_attempts": [1]}},
        "budget.max_attempts",
        "valid integer",
        "whole number",
    ),
    (
        "word-usd",
        {"budget": {"max_usd": "cheap"}},
        "budget.max_usd",
        "valid number",
        "use a number",
    ),
    ("list-usd", {"budget": {"max_usd": [1]}}, "budget.max_usd", "valid number", "use a number"),
]


@pytest.mark.parametrize(
    ("changes", "where", "message", "hint"),
    [case[1:] for case in FIELD_REJECTIONS],
    ids=[case[0] for case in FIELD_REJECTIONS],
)
def test_each_field_rule_rejects_with_a_hint(
    tmp_path: Path, changes: dict[str, Any], where: str, message: str, hint: str
) -> None:
    report = lint_path(write(tmp_path, changed(**changes)))
    assert report.specs == []
    assert len(report.problems) == 1, report.problems
    problem = report.problems[0]
    assert problem.where == where
    assert message in problem.message.lower()
    assert hint in problem.hint
    assert problem.hint != GENERIC_HINT


@pytest.mark.parametrize(
    "gate_config",
    [
        "target/tests/CONFTEST.py",  # Windows paths are case-insensitive
        "target/tests/conftest.py.",  # Windows drops trailing dots
        "target/ruff.toml",
        "target/guard_ops/.ruff.toml",
        "target/pytest.ini",
        "target/.coveragerc",
        "target/sitecustomize.py",
        "target/guard_ops/evil.pth",
    ],
)
def test_gate_config_files_are_never_allowed(tmp_path: Path, gate_config: str) -> None:
    (problem,) = lint_path(write(tmp_path, changed(allowed_paths=[gate_config]))).problems
    assert "configures the gates" in problem.message


def test_yaml_merge_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "GO-001.yaml"
    text = yaml.safe_dump(changed(budget=REMOVE), sort_keys=False)
    path.write_text(
        "defaults: &d\n  max_attempts: 2\n" + text + "budget:\n  <<: *d\n  max_usd: 1\n",
        encoding="utf-8",
    )
    (problem,) = lint_path(path).problems
    assert "merge keys" in problem.message
    assert "line" in problem.hint


def test_every_problem_is_reported_at_once(tmp_path: Path) -> None:
    report = lint_path(write(tmp_path, changed(id="bad", risk="none", allowed_paths=[])))
    assert sorted(problem.where for problem in report.problems) == ["allowed_paths", "id", "risk"]


# --- file-level rejections --------------------------------------------------


def test_invalid_yaml_names_the_line(tmp_path: Path) -> None:
    path = tmp_path / "GO-001.yaml"
    path.write_text("id: GO-001\ntitle: [unclosed\n", encoding="utf-8")
    (problem,) = lint_path(path).problems
    assert "not valid YAML" in problem.message
    assert "line 2" in problem.hint


def test_duplicate_keys_are_rejected_not_silently_overwritten(tmp_path: Path) -> None:
    # A reviewer reading the first allowed_paths must see what gets enforced.
    path = tmp_path / "GO-001.yaml"
    text = yaml.safe_dump(changed(allowed_paths=["acceptance/GO-001/test_x.py"]), sort_keys=False)
    path.write_text(text + "allowed_paths:\n  - target/guard_ops/db.py\n", encoding="utf-8")
    report = lint_path(path)
    assert report.specs == []
    (problem,) = report.problems
    assert "duplicate key 'allowed_paths'" in problem.message
    assert f"line {len(text.splitlines()) + 1}" in problem.hint


def test_id_mismatch_is_reported_with_other_problems(tmp_path: Path) -> None:
    report = lint_path(write(tmp_path, changed(risk="medium"), "GO-002.yaml"))
    assert sorted(problem.where for problem in report.problems) == ["id", "risk"]


def test_upper_case_suffix_is_still_linted(tmp_path: Path) -> None:
    write(tmp_path, valid_spec(), "GO-001.YAML")
    assert [spec.id for spec in lint_path(tmp_path).specs] == ["GO-001"]


def test_single_file_must_be_yaml(tmp_path: Path) -> None:
    (problem,) = lint_path(write(tmp_path, valid_spec(), "GO-001.txt")).problems
    assert "not a spec file" in problem.message
    assert ".yaml" in problem.hint


def test_non_utf8_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "GO-001.yaml"
    path.write_bytes(b"id: GO-001\ntitle: caf\xe9\n")
    (problem,) = lint_path(path).problems
    assert "could not read file" in problem.message
    assert "UTF-8" in problem.hint


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "GO-001.yaml"
    path.write_text("", encoding="utf-8")
    (problem,) = lint_path(path).problems
    assert "empty" in problem.message


def test_top_level_must_be_a_mapping(tmp_path: Path) -> None:
    (problem,) = lint_path(write(tmp_path, ["id", "GO-001"])).problems
    assert "mapping" in problem.message


def test_missing_path_is_rejected(tmp_path: Path) -> None:
    (problem,) = lint_path(tmp_path / "nope.yaml").problems
    assert "does not exist" in problem.message


def test_directory_without_specs_is_rejected(tmp_path: Path) -> None:
    (problem,) = lint_path(tmp_path).problems
    assert "no spec files" in problem.message
    assert problem.hint != GENERIC_HINT


def test_id_must_match_the_file_name(tmp_path: Path) -> None:
    (problem,) = lint_path(write(tmp_path, valid_spec(), "GO-002.yaml")).problems
    assert problem.where == "id"
    assert problem.message == "GO-001 does not match the file name GO-002.yaml"
    assert "GO-001.yaml" in problem.hint


def test_duplicate_ids_in_a_directory_are_rejected(tmp_path: Path) -> None:
    write(tmp_path, valid_spec(), "GO-001.yaml")
    write(tmp_path, valid_spec(), "GO-001.yml")
    report = lint_path(tmp_path)
    (problem,) = report.problems
    assert problem.file.name == "GO-001.yml"
    assert "already used by GO-001.yaml" in problem.message
    assert [spec.id for spec in report.specs] == ["GO-001"]


# --- load_spec and rendering ------------------------------------------------


def test_load_spec_raises_with_every_problem(tmp_path: Path) -> None:
    with pytest.raises(SpecError) as caught:
        load_spec(write(tmp_path, changed(id="bad", risk="none")))
    assert len(caught.value.problems) == 2
    assert "2 problems" in str(caught.value)


def test_problem_renders_location_message_and_fix(tmp_path: Path) -> None:
    path = write(tmp_path, changed(allowed_paths=["pyproject.toml"]))
    (problem,) = lint_path(path).problems
    first, second = problem.render().splitlines()
    assert first.startswith(f"{path}: allowed_paths[0]: ")
    assert second.startswith("  fix: ")
