"""Spec model and the spec gate.

A spec that fails the gate goes back to its author and costs zero tokens.
Every rejection names the file and field, says what is wrong, and how to fix it.

The gate fails early and cheaply; it is not the security boundary. The runtime
tools (T2.3) still resolve every path and re-check it against the allowlist.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
)
from pydantic_core import ErrorDetails, PydanticCustomError

TARGET_ROOT = "target/"
MAX_ATTEMPTS_CAP = 5
MAX_USD_CAP = 5.0
SPEC_SUFFIXES = (".yaml", ".yml")
GENERIC_HINT = "check this field against the Spec model in factory/spec.py"
REQUIRED_FIELDS = "id, title, goal, acceptance_criteria, allowed_paths, risk"

# Files that configure the gates (pytest, ruff, mypy, coverage, the interpreter).
# Compared case-insensitively with trailing dots/spaces removed, as Windows does.
GATE_CONFIG_NAMES = frozenset(
    {
        "conftest.py",
        "pytest.ini",
        ".pytest.ini",
        "pyproject.toml",
        "tox.ini",
        "setup.cfg",
        "ruff.toml",
        ".ruff.toml",
        "mypy.ini",
        ".mypy.ini",
        ".coveragerc",
        "sitecustomize.py",
        "usercustomize.py",
    }
)
ID_PATTERN = r"^[A-Z]{2,5}-\d{3}$"
_DRIVE_LETTER = re.compile(r"^[A-Za-z]:")
_CONTROL_OR_BRACE = re.compile(r"[\x00-\x1f\x7f{}]")


# --- YAML loading -----------------------------------------------------------


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate and merge keys, so what a reviewer reads is what runs."""


_MERGE_TAG = "tag:yaml.org,2002:merge"


def _construct_mapping_once(loader: yaml.SafeLoader, node: yaml.Node) -> dict[Any, Any]:
    assert isinstance(node, yaml.MappingNode)  # noqa: S101 - the mapping tag only yields these
    seen: list[Any] = []  # a list, not a set: YAML keys may be unhashable
    for key_node, _ in node.value:
        if key_node.tag == _MERGE_TAG:
            # A merge lets a local key silently override the anchor's value.
            raise yaml.constructor.ConstructorError(
                None, None, "YAML merge keys (<<) are not allowed in specs", key_node.start_mark
            )
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key '{key}'", key_node.start_mark
            )
        seen.append(key)
    return loader.construct_mapping(node)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping_once
)


# --- the model --------------------------------------------------------------


def _check_allowed_path(path: str) -> str:
    """Keep every allowed path a narrow, plain path inside target/."""
    context = {"path": repr(path)}

    def reject(kind: str, what: str) -> PydanticCustomError:
        return PydanticCustomError(kind, "path {path} " + what, context)

    if _CONTROL_OR_BRACE.search(path):
        raise reject("path_bad_chars", "contains control characters or braces")
    if "\\" in path:
        raise reject("path_backslash", "uses backslashes")
    if path.startswith("/") or _DRIVE_LETTER.match(path):
        raise reject("path_absolute", "is absolute")
    if path.startswith("./"):
        raise reject("path_dot_prefix", "starts with './'")
    if ".." in PurePosixPath(path).parts:
        raise reject("path_parent", "contains '..'")
    if not path.startswith(TARGET_ROOT):
        raise reject("path_outside_target", "is not inside target/")
    # A typo guard for the obvious catch-alls, not a guarantee: `target/**/*.py` is
    # nearly as broad. Breadth is for the human reviewing the spec to judge.
    if not path[len(TARGET_ROOT) :].strip("*/"):
        raise reject("path_catch_all", "allows all of target/")
    name = PurePosixPath(path).name.lower().rstrip(". ")
    if name in GATE_CONFIG_NAMES or name.endswith(".pth"):
        raise reject("path_gate_config", "names a file that configures the gates")
    return path


def _reject_bool(value: Any) -> Any:
    # YAML reads `true` and `yes` as booleans, which Pydantic would accept as 1.
    if isinstance(value, bool):
        raise PydanticCustomError("bool_not_number", "true/false is not a number")
    return value


Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
AllowedPath = Annotated[Line, AfterValidator(_check_allowed_path)]


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_attempts: Annotated[int, BeforeValidator(_reject_bool)] = Field(
        default=3, ge=1, le=MAX_ATTEMPTS_CAP
    )
    max_usd: Annotated[float, BeforeValidator(_reject_bool)] = Field(
        default=1.0, gt=0, le=MAX_USD_CAP
    )


class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # The id also names acceptance/<id>/, so the pattern keeps it a safe folder name.
    id: Annotated[str, StringConstraints(strip_whitespace=True, pattern=ID_PATTERN)]
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    goal: Line
    acceptance_criteria: list[Line] = Field(min_length=1)
    allowed_paths: list[AllowedPath] = Field(min_length=1)
    risk: Literal["low", "high"]
    budget: Budget = Field(default_factory=Budget)


class Problem(BaseModel):
    """One reason a spec was rejected. `where` is the field path, empty for file-level problems."""

    model_config = ConfigDict(frozen=True)

    file: Path
    where: str = ""
    message: str
    hint: str

    def render(self) -> str:
        location = f"{self.file}: {self.where}: " if self.where else f"{self.file}: "
        return f"{location}{self.message}\n  fix: {self.hint}"


class LintReport(BaseModel):
    specs: list[Spec] = Field(default_factory=list)
    problems: list[Problem] = Field(default_factory=list)


class SpecError(Exception):
    def __init__(self, problems: list[Problem]) -> None:
        self.problems = problems
        count = f"{len(problems)} problem{'s' if len(problems) != 1 else ''}"
        details = "\n".join(problem.render() for problem in problems)
        super().__init__(f"spec rejected with {count}:\n{details}")


# --- fix hints --------------------------------------------------------------

# Keyed by Pydantic error type. Templates may use {field}, {article} and the
# error's own context (e.g. {le}, {max_length}, {expected}).
HINTS: dict[str, str] = {
    "missing": "add {article} `{field}:` entry",
    "string_pattern_mismatch": "use an id like GO-001: 2 to 5 capital letters, a dash, 3 digits",
    "string_too_short": "give it a non-empty value",
    "string_too_long": "shorten it to at most {max_length} characters",
    "string_type": "use plain text",
    "too_short": "add at least one item",
    "list_type": "write it as a YAML list, one `- item` per line",
    "model_type": "write it as a YAML mapping of `key: value` lines",
    "literal_error": "use {expected}",
    "less_than_equal": "use a value of at most {le}",
    "greater_than_equal": "use a value of at least {ge}",
    "greater_than": "use a value above {gt}",
    "int_type": "use a whole number",
    "int_parsing": "use a whole number",
    "int_from_float": "use a whole number",
    "float_type": "use a number, e.g. 0.5",
    "float_parsing": "use a number, e.g. 0.5",
    "bool_not_number": "use a number, not true/false",
    "path_bad_chars": "write a plain path; brace globs and control characters are not allowed",
    "path_backslash": "use forward slashes, e.g. target/guard_ops/db.py",
    "path_absolute": "make it relative to the repo root, e.g. target/guard_ops/db.py",
    "path_dot_prefix": "drop the leading './', e.g. target/guard_ops/db.py",
    "path_parent": "write the path without '..' segments, starting at target/",
    "path_outside_target": (
        "list files or globs under target/; a spec may never let the agent edit "
        "acceptance tests, gate config or the factory"
    ),
    "path_catch_all": "name the files or folders the change needs, e.g. target/guard_ops/routes/*",
    "path_gate_config": (
        "remove it; test, lint, type and interpreter configuration (conftest.py, "
        "pytest.ini, ruff.toml, .pth, ...) can change how the gates judge every file, "
        "so only a human edits it"
    ),
}


def _where(loc: tuple[int | str, ...]) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else part
    return out


def _unknown_field_hint(loc: tuple[int | str, ...]) -> str:
    field = str(loc[-1])
    model: type[BaseModel] = Budget if loc[:1] == ("budget",) else Spec
    known = list(model.model_fields)
    close = difflib.get_close_matches(field, known, n=1)
    suggestion = f"; did you mean `{close[0]}`?" if close else ""
    return f"remove `{field}`{suggestion} (known fields: {', '.join(known)})"


def _hint(error: ErrorDetails) -> str:
    loc = error["loc"]
    if error["type"] == "extra_forbidden":
        return _unknown_field_hint(loc)
    template = HINTS.get(error["type"])
    field = str(loc[-1]) if loc else "field"
    article = "an" if field[:1].lower() in "aeiou" else "a"
    context: dict[str, Any] = dict(error.get("ctx", {}))
    try:
        return (
            template.format(field=field, article=article, **context) if template else GENERIC_HINT
        )
    except KeyError:  # pragma: no cover - a template naming context its error lacks
        return GENERIC_HINT


# --- the gate ---------------------------------------------------------------


def _yaml_problem(path: Path, exc: yaml.YAMLError) -> Problem:
    hint = "fix the YAML"
    if isinstance(exc, yaml.MarkedYAMLError):
        mark = exc.context_mark or exc.problem_mark
        if mark is not None:  # pragma: no branch - PyYAML marks syntax errors
            hint += f" near line {mark.line + 1}"
        reason = exc.problem or "parse error"
    else:  # pragma: no cover - PyYAML raises marked errors for syntax problems
        reason = str(exc)
    return Problem(file=path, message=f"not valid YAML: {reason}", hint=hint)


def _read(path: Path) -> tuple[Any, Problem | None]:
    if not path.is_file():
        hint = "pass a spec file or a directory of specs, e.g. specs/"
        return None, Problem(file=path, message="path does not exist", hint=hint)
    if path.suffix.lower() not in SPEC_SUFFIXES:
        hint = f"name spec files <id>.yaml or <id>.yml (got '{path.suffix}')"
        return None, Problem(file=path, message="not a spec file", hint=hint)
    try:
        text = path.read_text(encoding="utf-8")
        return yaml.load(text, Loader=_StrictLoader), None  # noqa: S506 - a SafeLoader subclass
    except yaml.YAMLError as exc:
        return None, _yaml_problem(path, exc)
    except (OSError, UnicodeDecodeError) as exc:
        message = f"could not read file: {exc}"
        return None, Problem(file=path, message=message, hint="save the spec as UTF-8 text")


def _check_file(path: Path) -> tuple[Spec | None, list[Problem]]:
    """Return the spec if it passes the gate, else every problem found."""
    raw, problem = _read(path)
    if problem is not None:
        return None, [problem]
    if raw is None:
        message, hint = "file is empty", f"add the fields {REQUIRED_FIELDS}"
        return None, [Problem(file=path, message=message, hint=hint)]
    if not isinstance(raw, dict):
        message = f"top level must be a mapping of fields, got a {type(raw).__name__}"
        hint = f"write `key: value` lines for {REQUIRED_FIELDS}"
        return None, [Problem(file=path, message=message, hint=hint)]

    problems: list[Problem] = []
    raw_id = raw.get("id")
    spec_id = raw_id.strip() if isinstance(raw_id, str) else ""
    # Only a well-formed id can be compared; a malformed one already gets its own problem.
    if re.fullmatch(ID_PATTERN, spec_id) and spec_id != path.stem:
        problems.append(
            Problem(
                file=path,
                where="id",
                message=f"{spec_id} does not match the file name {path.name}",
                hint=f"rename the file to {spec_id}{path.suffix} or set `id: {path.stem}`",
            )
        )
    try:
        spec = Spec.model_validate(raw)
    except ValidationError as exc:
        problems += [
            Problem(file=path, where=_where(err["loc"]), message=err["msg"], hint=_hint(err))
            for err in exc.errors()
        ]
        return None, problems
    return (None, problems) if problems else (spec, [])


def load_spec(path: Path) -> Spec:
    """Load one spec through the gate. Raises SpecError listing every problem."""
    spec, problems = _check_file(path)
    if spec is None:
        raise SpecError(problems)
    return spec


def lint_path(path: Path) -> LintReport:
    """Run the spec gate on a file, or on every *.yaml / *.yml file in a directory."""
    if path.is_dir():
        files = sorted(
            p for p in path.iterdir() if p.is_file() and p.suffix.lower() in SPEC_SUFFIXES
        )
        if not files:
            problem = Problem(
                file=path,
                message="no spec files (*.yaml, *.yml) in this directory",
                hint="add a spec such as GO-001.yaml, or pass a single spec file",
            )
            return LintReport(problems=[problem])
    else:
        files = [path]

    report = LintReport()
    seen: dict[str, Path] = {}
    for file in files:
        spec, problems = _check_file(file)
        report.problems.extend(problems)
        if spec is None:
            continue
        if spec.id in seen:
            report.problems.append(
                Problem(
                    file=file,
                    where="id",
                    message=f"{spec.id} is already used by {seen[spec.id].name}",
                    hint="give each spec a unique id; acceptance tests are found by spec id",
                )
            )
            continue
        seen[spec.id] = file
        report.specs.append(spec)
    return report
