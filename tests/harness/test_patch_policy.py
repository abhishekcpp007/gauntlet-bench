"""`patch:<file>` applies a patch from a file the way the oracle applies the real fix. Offline."""

import ast
import shutil
import subprocess
import types
from pathlib import Path

import pytest

from gauntlet.harness import policies
from gauntlet.harness.policies import ORACLE_EOF, OraclePolicy, PatchPolicy, make_policy
from gauntlet.harness.runner import episode_id

from .test_policies import FakeEnv

BASE_COMMIT = "72d3788256aa8fa9e26930a400437b16888bfaf3"
POLICIES_PATH = "src/gauntlet/harness/policies.py"
REPO_ROOT = Path(__file__).resolve().parents[2]
CHANGED = {"OraclePolicy", "make_policy"}
ADDED = {"_AppliesPatch", "PATCH_PREFIX", "PatchPolicy", "import hashlib", "from pathlib import Path"}
BIG_PATCH_LINES = 30_000
SMALL = "diff --git a/x.py b/x.py\n+fixed\n"
BIG = "diff --git a/x.py b/x.py\n" + "".join(f"+line {i}\n" for i in range(BIG_PATCH_LINES))
NO_NEWLINE = "diff --git a/x.py b/x.py\n+no newline at the end"
BLANK = "  \n"
SENTINEL_PATCH = f"+{ORACLE_EOF}\n"
SAMPLE_PATCHES = (SMALL, BIG, NO_NEWLINE)
SHORT_STEPS = 2
ROOMY_STEPS = 50
SHA256_HEX_LENGTH = 64


def _base_source() -> str | None:
    if shutil.which("git") is None:
        return None
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{BASE_COMMIT}:{POLICIES_PATH}"],
        capture_output=True,
        text=True,
    )
    return proc.stdout if proc.returncode == 0 else None


BASE_SOURCE = _base_source()
needs_base = pytest.mark.skipif(BASE_SOURCE is None, reason="the base commit isn't in this checkout")


def _base_module() -> types.ModuleType:
    module = types.ModuleType("gauntlet.harness._policies_at_base")
    module.__package__ = "gauntlet.harness"
    exec(compile(BASE_SOURCE, POLICIES_PATH, "exec"), module.__dict__)
    return module


def _top_level(source: str) -> dict[str, str]:
    names: dict[str, str] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef | ast.ClassDef):
            names[node.name] = ast.dump(node)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names[target.id] = ast.dump(node)
        else:
            names[ast.unparse(node)] = ast.dump(node)
    return names


def _write(tmp_path: Path, text: str, name: str = "fix.diff") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


@needs_base
@pytest.mark.parametrize("gold", SAMPLE_PATCHES, ids=("small", "big", "no-newline"))
@pytest.mark.parametrize("max_steps", (ROOMY_STEPS, SHORT_STEPS), ids=("room", "truncated"))
def test_oracle_sends_byte_identical_actions_to_the_base_commit(gold, max_steps):
    before, after = FakeEnv(gold=gold, max_steps=max_steps), FakeEnv(gold=gold, max_steps=max_steps)
    old = _base_module().OraclePolicy()
    new = OraclePolicy()
    old.run(before)
    new.run(after)
    assert after.actions == before.actions
    assert new.messages == old.messages
    assert (new.name, new.params()) == (old.name, old.params())


@needs_base
def test_oracle_refuses_the_sentinel_with_the_same_message():
    gold = f"diff --git a/x.py b/x.py\n+{ORACLE_EOF}\n"
    with pytest.raises(RuntimeError) as old:
        _base_module().OraclePolicy().run(FakeEnv(gold=gold))
    with pytest.raises(RuntimeError) as new:
        OraclePolicy().run(FakeEnv(gold=gold))
    assert str(new.value) == str(old.value)


@needs_base
def test_every_other_top_level_name_is_untouched():
    before = _top_level(BASE_SOURCE)
    after = _top_level(Path(policies.__file__).read_text())
    assert set(after) - set(before) == ADDED
    assert set(before) <= set(after)
    for name in sorted(set(before) - CHANGED):
        assert after[name] == before[name], name


def test_zoo_payloads_are_untouched_by_name():
    assert set(policies.ZOO) == {
        "monkeypatch",
        "stealth",
        "rewrite",
        "canary-aware",
        "ghost",
        "junit",
        "exit",
        "snapshot",
    }


def test_oracle_commands_for_a_small_patch():
    env = FakeEnv(gold=SMALL)
    OraclePolicy().run(env)
    assert env.actions == [
        {"type": "bash", "command": f"cat > /tmp/oracle.diff <<'{ORACLE_EOF}'\n{SMALL}{ORACLE_EOF}"},
        {"type": "bash", "command": "git apply /tmp/oracle.diff"},
        {"type": "submit"},
    ]


@pytest.mark.parametrize("text", SAMPLE_PATCHES, ids=("small", "big", "no-newline"))
def test_patch_sends_what_the_oracle_would_send_for_the_same_diff(tmp_path, text):
    oracle_env, patch_env = FakeEnv(gold=text), FakeEnv(gold="unused")
    OraclePolicy().run(oracle_env)
    make_policy(f"patch:{_write(tmp_path, text)}").run(patch_env)
    assert patch_env.actions == oracle_env.actions
    assert patch_env.submitted


def test_patch_stops_when_the_env_truncates(tmp_path):
    env = FakeEnv(max_steps=1)
    make_policy(f"patch:{_write(tmp_path, SMALL)}").run(env)
    assert len(env.actions) == 1


def test_make_policy_builds_a_patch_policy_named_after_the_file(tmp_path):
    path = _write(tmp_path, SMALL, "my-answer.diff")
    policy = make_policy(f"patch:{path}")
    assert isinstance(policy, PatchPolicy)
    assert policy.name == "patch:my-answer.diff"
    assert policy.params()["patch"] == str(path)
    assert len(policy.params()["sha256"]) == SHA256_HEX_LENGTH


def test_two_patches_with_one_file_name_share_a_name_but_not_an_episode(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a, b = _write(tmp_path / "a", SMALL), _write(tmp_path / "b", SMALL + "+more\n")
    first, second = make_policy(f"patch:{a}"), make_policy(f"patch:{b}")
    assert first.name == second.name
    assert first.params()["sha256"] != second.params()["sha256"]
    task = types.SimpleNamespace(instance_id="owner__repo-1")
    assert episode_id(task, f"patch:{a}", 0) != episode_id(task, f"patch:{b}", 0)


def test_episode_id_from_a_path_with_slashes_is_filesystem_safe(tmp_path):
    spec = f"patch:{_write(tmp_path, SMALL)}"
    eid = episode_id(types.SimpleNamespace(instance_id="owner__repo-1"), spec, 0)
    assert "/" not in eid and ":" not in eid
    assert eid.startswith("owner__repo-1__patch-") and eid.endswith("fix.diff__0")


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("patch:", "needs a file"),
        ("patch:/no/such/fix.diff", "no patch file"),
    ],
)
def test_bad_specs_fail_with_a_plain_message(spec, message):
    with pytest.raises(ValueError, match=message):
        make_policy(spec)


def test_an_empty_patch_fails(tmp_path):
    with pytest.raises(ValueError, match="is empty"):
        make_policy(f"patch:{_write(tmp_path, BLANK)}")


def test_a_folder_is_unreadable(tmp_path):
    with pytest.raises(ValueError, match="couldn't read"):
        make_policy(f"patch:{tmp_path}")


def test_a_patch_that_isnt_text_is_unreadable(tmp_path):
    path = tmp_path / "fix.diff"
    path.write_bytes(b"\xff\xfe\x00 not utf-8")
    with pytest.raises(ValueError, match="couldn't read"):
        make_policy(f"patch:{path}")


def test_a_comma_in_the_path_is_refused(tmp_path):
    path = _write(tmp_path, SMALL, "a,b.diff")
    with pytest.raises(ValueError, match="comma"):
        make_policy(f"patch:{path}")


def test_the_heredoc_sentinel_is_refused(tmp_path):
    with pytest.raises(ValueError, match=ORACLE_EOF):
        make_policy(f"patch:{_write(tmp_path, SENTINEL_PATCH)}")


def test_runner_checks_every_spec_before_a_sandbox_starts(tmp_path, monkeypatch):
    from gauntlet.harness import runner

    def no_sandbox(*_, **__):
        raise AssertionError("a sandbox started")

    monkeypatch.setattr(runner, "SWEEnv", no_sandbox)
    with pytest.raises(ValueError, match="no patch file"):
        runner.run([], ["oracle", f"patch:{tmp_path / 'missing.diff'}"], out_dir=tmp_path / "out")
