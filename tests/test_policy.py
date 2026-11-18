"""Diff policy (T1.6): each rule fires on a small sample diff, and its near-misses don't."""

from __future__ import annotations

from pathlib import Path

import pytest

from factory.gates import policy_check, run_gates
from factory.policy import Violation, check_diff, parse_diff
from factory.sandbox import SandboxResult


def added(path: str, *lines: str, start: int = 1) -> str:
    """A git diff that adds `lines` to an existing file at `path`."""
    body = "".join(f"+{line}\n" for line in lines)
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        f"@@ -{start},0 +{start},{len(lines)} @@\n{body}"
    )


def removed(path: str, *lines: str) -> str:
    body = "".join(f"-{line}\n" for line in lines)
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        f"@@ -1,{len(lines)} +0,0 @@\n{body}"
    )


def rules(diff: str) -> list[str]:
    return [violation.rule for violation in check_diff(diff)]


APP = "target/guard_ops/routes/tours.py"
TESTS = "target/tests/test_tours.py"

# --- each rule fires ---------------------------------------------------------

FIRES = [
    ("aws-key", added(APP, 'KEY = "AKIAABCDEFGHIJKLMNOP"'), "secret"),
    ("api-key", added(APP, 'client = Client("sk-ant-abcdefghijklmnopqrstuv")'), "secret"),
    ("github-token", added(APP, "t = 'ghp_" + "a" * 36 + "'"), "secret"),
    ("private-key", added("target/key.pem", "-----BEGIN RSA PRIVATE KEY-----"), "secret"),
    ("credential", added(APP, 'db_password = "hunter2hunter2"'), "secret"),
    ("credential-upper", added(APP, 'API_TOKEN = "abcd1234efgh5678"'), "secret"),
    ("subprocess-import", added(APP, "import subprocess"), "banned-call"),
    ("subprocess-from", added(APP, "from subprocess import run"), "banned-call"),
    ("os-system", added(APP, 'os.system("rm -rf /")'), "banned-call"),
    ("os-popen", added(APP, 'os.popen("ls")'), "banned-call"),
    ("eval", added(APP, "value = eval(text)"), "banned-call"),
    ("exec", added(APP, "exec(code)"), "banned-call"),
    ("deleted-test", removed(TESTS, "def test_unknown_tag_is_rejected(client):"), "deleted-test"),
    ("mark-skip", added(TESTS, '@pytest.mark.skip(reason="flaky")'), "skipped-test"),
    ("mark-skipif", added(TESTS, "@pytest.mark.skipif(True, reason='x')"), "skipped-test"),
    ("mark-xfail", added(TESTS, "@pytest.mark.xfail"), "skipped-test"),
    ("runtime-skip", added(TESTS, '    pytest.skip("not today")'), "skipped-test"),
    ("importorskip", added(TESTS, 'np = pytest.importorskip("numpy")'), "skipped-test"),
    ("custom-marker", added(TESTS, "@pytest.mark.live"), "test-marker"),
    ("module-marker", added(TESTS, "pytestmark = []"), "test-marker"),
    ("no-cover", added(APP, "    return 1  # pragma: no cover"), "gate-comment"),
    ("no-branch", added(APP, "    if x:  # pragma: no branch"), "gate-comment"),
    ("type-ignore", added(APP, "x: int = 'a'  # type: ignore[assignment]"), "gate-comment"),
    ("noqa", added(APP, "import os  # noqa: F401"), "gate-comment"),
    (
        "hook",
        added("target/tests/plugin.py", "def pytest_collection_modifyitems(items):"),
        "pytest-hook",
    ),
    ("conftest", added("target/tests/conftest.py", "X = 1"), "gate-config"),
    ("pyproject", added("pyproject.toml", "fail_under = 0"), "gate-config"),
    ("ruff-toml", added("target/ruff.toml", "[lint]"), "gate-config"),
    ("pth", added("target/hook.pth", "import os"), "gate-config"),
    ("case-variant", added("target/tests/CONFTEST.py", "X = 1"), "gate-config"),
]


@pytest.mark.parametrize(
    ("diff", "rule"), [case[1:] for case in FIRES], ids=[case[0] for case in FIRES]
)
def test_each_rule_fires_on_a_sample_diff(diff: str, rule: str) -> None:
    assert rule in rules(diff)


# --- and its near-misses don't ------------------------------------------------

QUIET = [
    ("execute", added(APP, "db.execute('SELECT 1')")),
    ("literal-eval", added(APP, "value = ast.literal_eval(text)")),
    ("method-eval", added(APP, "model.eval()")),
    ("word-subprocesses", added(APP, "# subprocesses are not used here")),
    ("short-sk", added(APP, 'prefix = "sk-"')),
    ("password-field", added(APP, "password: str = Field(min_length=8)")),
    ("parametrize", added(TESTS, '@pytest.mark.parametrize("x", [1, 2])')),
    ("usefixtures", added(TESTS, '@pytest.mark.usefixtures("client")')),
    ("plain-test", added(TESTS, "def test_new_behaviour(client):", "    assert True")),
    (
        "context-noqa",
        (
            f"diff --git a/{APP} b/{APP}\n--- a/{APP}\n+++ b/{APP}\n"
            "@@ -1,2 +1,3 @@\n import os  # noqa: F401\n+x = 1\n y = 2\n"
        ),
    ),
    ("removed-noqa", removed(APP, "import os  # noqa: F401")),
    ("markdown-not-python", added("docs/notes.md", "eval(x) and @pytest.mark.skip")),
]


@pytest.mark.parametrize("diff", [case[1] for case in QUIET], ids=[case[0] for case in QUIET])
def test_near_misses_are_not_flagged(diff: str) -> None:
    assert check_diff(diff) == []


def test_banned_calls_only_apply_to_target_code() -> None:
    assert rules(added("evals/run_all.py", "import subprocess")) == []


def test_a_renamed_or_moved_test_is_not_deleted() -> None:
    renamed = removed(TESTS, "def test_old_name(client):") + added(
        "target/tests/test_scans.py", "def test_old_name(client):"
    )
    assert rules(renamed) == []


def test_secrets_are_never_shown_in_full() -> None:
    fake_key = "sk-ant-" + "abcdefghijklmnopqrstuvwxyz0123"  # built, so no real-looking literal
    (violation,) = check_diff(added(APP, f'KEY = "{fake_key}"'))
    rendered = violation.render()
    assert fake_key not in rendered
    assert "redacted" in rendered


def test_violations_carry_file_and_new_line_number() -> None:
    (violation,) = check_diff(added(APP, "x = 1", "y = eval(z)", start=10))
    assert (violation.path, violation.line) == (APP, 11)
    assert violation.render().startswith(f"{APP}:11 [banned-call] eval: ")


def test_every_violation_is_reported() -> None:
    diff = added(APP, "import subprocess", "x = eval(y)  # noqa: S307") + removed(
        TESTS, "def test_gone():"
    )
    assert sorted(rules(diff)) == ["banned-call", "banned-call", "deleted-test", "gate-comment"]


# --- parsing -----------------------------------------------------------------


def test_parser_handles_new_deleted_and_renamed_files() -> None:
    diff = (
        "diff --git a/target/new.py b/target/new.py\nnew file mode 100644\n"
        "--- /dev/null\n+++ b/target/new.py\n@@ -0,0 +1 @@\n+x = 1\n"
        "diff --git a/target/old.py b/target/old.py\ndeleted file mode 100644\n"
        "--- a/target/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-y = 2\n"
        "diff --git a/target/tests/conftest.py b/target/tests/fixtures.py\n"
        "similarity index 100%\nrename from target/tests/conftest.py\n"
        "rename to target/tests/fixtures.py\n"
    )
    new, old, moved = parse_diff(diff)
    assert (new.old_path, new.new_path, new.added) == (None, "target/new.py", [(1, "x = 1")])
    assert (old.old_path, old.new_path, old.removed) == ("target/old.py", None, ["y = 2"])
    assert moved.paths == {"target/tests/conftest.py", "target/tests/fixtures.py"}
    # Renaming conftest.py away is a gate-config change too.
    assert "gate-config" in rules(diff)


def test_plain_multi_file_diff_with_dashes_in_content() -> None:
    # A removed line starting with "--" must not be read as the next file's header.
    diff = (
        "--- a/target/a.py\n+++ b/target/a.py\n@@ -1,2 +1,1 @@\n"
        "--- a comment that starts with dashes\n x = 1\n"
        "--- a/target/b.py\n+++ b/target/b.py\n@@ -1 +1,2 @@\n y = 2\n+z = eval(y)\n"
    )
    a, b = parse_diff(diff)
    assert a.removed == ["-- a comment that starts with dashes"]
    assert (b.path, b.added) == ("target/b.py", [(2, "z = eval(y)")])
    assert rules(diff) == ["banned-call"]


def test_crlf_and_no_newline_marker_are_handled() -> None:
    diff = (
        f"diff --git a/{APP} b/{APP}\r\n--- a/{APP}\r\n+++ b/{APP}\r\n"
        "@@ -1 +1 @@\r\n-x = 1\r\n\\ No newline at end of file\r\n+x = eval('1')\r\n"
        "\\ No newline at end of file\r\n"
    )
    (f,) = parse_diff(diff)
    assert f.added == [(1, "x = eval('1')")]
    assert rules(diff) == ["banned-call"]


def test_empty_diff_has_no_violations() -> None:
    assert check_diff("") == []


# --- as a gate check ----------------------------------------------------------


def test_policy_check_summarizes_rules_and_lists_each_violation() -> None:
    check = policy_check(added(APP, "import subprocess", "x = 1  # noqa"))
    assert (check.name, check.passed) == ("policy", False)
    assert check.summary == "2 policy violations: banned-call, gate-comment"
    assert check.details.count("\n") == 1


def test_clean_diff_passes_the_policy_check() -> None:
    check = policy_check(added(APP, "x = 1"))
    assert (check.passed, check.summary) == (True, "no policy violations")


def test_run_gates_adds_the_policy_check_only_when_given_a_diff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "target").mkdir()
    for name in ("pyproject.toml", "uv.lock"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    passing = SandboxResult(
        mode="local",
        isolated=False,
        command=["x"],
        exit_code=0,
        timed_out=False,
        output_overflow=False,
        stdout="ok\n",
        stderr="",
        duration_s=0.1,
    )
    monkeypatch.setattr("factory.gates.run", lambda *args, **kwargs: passing)
    # The workspace is its own reference, so the config-integrity check passes.
    without = run_gates(tmp_path, mode="local", reference=tmp_path)
    assert "policy" not in [check.name for check in without.checks]
    with_diff = run_gates(tmp_path, mode="local", reference=tmp_path, diff=added(APP, "exec(x)"))
    assert with_diff.failed == ["policy"]


def test_violation_without_line_renders_path_only() -> None:
    violation = Violation(rule="deleted-test", path=TESTS, line=None, detail="removed test_x")
    assert violation.render() == f"{TESTS} [deleted-test] removed test_x"
