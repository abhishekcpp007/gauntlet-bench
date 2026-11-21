"""Env builds on a real container, and a big patch read back out of one."""

import docker
import pytest

from gauntlet.envs import build_env, extract_patch
from gauntlet.envs.env import BuildFailed, UnsupportedRepo

from .conftest import _commit, _git

pytestmark = pytest.mark.docker


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from .conftest import make_calc_repo

    root = tmp_path_factory.mktemp("e2e")
    repo = make_calc_repo(root)
    cache = root / "cache"
    env = build_env(str(repo), cache_dir=cache)
    yield env
    try:
        docker.from_env().images.remove(env.image, force=True)
    except docker.errors.APIError:
        pass


def test_env_baseline(built):
    env = built
    assert env.image.startswith("gauntlet-env/local__calc:")
    assert sorted(env.baseline.passed) == [
        "tests/test_calc.py::test_add",
        "tests/test_calc.py::test_mul",
        "tests/test_ops.py::TestSubMore::test_zero",
        "tests/test_ops.py::test_sub",
    ]


def test_env_image_keeps_no_scratch_or_caches(built):
    from gauntlet.sandbox import Sandbox, SandboxConfig

    env = built
    with Sandbox(SandboxConfig(image=env.image), record=False) as sb:
        res = sb.exec("ls -d /tmp/gauntlet-* /root/.cache 2>/dev/null | wc -l")
    assert res.stdout.strip() == "0"


def test_a_patch_past_the_output_cap_comes_back_whole(built):
    # release-range tasks have gold patches of 140 to 270 KB, and exec output is capped at 200 KB
    from gauntlet.envs import Task
    from gauntlet.sandbox import Sandbox, SandboxConfig

    env = built
    task = Task(
        instance_id="calc", repo=env.repo, image=env.image, workdir=env.workdir, base_commit=env.commit,
        solution_commit=env.commit, problem_statement="", gold_patch="", test_patch="", test_files=[],
        fail_to_pass=[], pass_to_pass=[],
    )  # fmt: skip
    table = "".join(f"ROW_{i:06d} = {i}\n" for i in range(20_000))  # about 330 KB
    with Sandbox(SandboxConfig(image=env.image, workdir=env.workdir), record=False) as sb:
        assert sb.exec(
            "git init -q && git add -A && git -c user.name=t -c user.email=t@t commit -q -m base"
        ).ok
        sb.write_file("calc/table.py", table)
        patch = extract_patch(sb, task)
    assert len(patch) > 300_000
    assert "+ROW_000000 = 0" in patch and "+ROW_019999 = 19999" in patch


def test_non_python_repo_is_refused(tmp_path):
    repo = tmp_path / "js"
    repo.mkdir()
    _git(repo, "init", "-q")
    _commit(repo, "init", {"package.json": "{}"})
    with pytest.raises(UnsupportedRepo, match="node"):
        build_env(str(repo), cache_dir=tmp_path / "cache")


LOUD_FAILING_SETUP = """\
import sys

sys.stderr.write("compiling a lot of things\\n" * 20000)
sys.exit("the actual reason the build broke")
"""


SETUPTOOLS_PYPROJECT = '[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n'


def test_a_failed_install_reports_its_last_words_past_the_output_cap(tmp_path):
    repo = tmp_path / "loud"
    repo.mkdir()
    _git(repo, "init", "-q")
    _commit(
        repo,
        "init",
        {
            "pyproject.toml": SETUPTOOLS_PYPROJECT,
            "setup.py": LOUD_FAILING_SETUP,
            "loud/__init__.py": "",
        },
    )
    with pytest.raises(BuildFailed, match="the actual reason the build broke"):
        build_env(str(repo), cache_dir=tmp_path / "cache")
