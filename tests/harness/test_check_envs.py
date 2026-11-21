"""`gauntlet check-envs`: a task whose env would rebuild on another fingerprint is caught. No Docker."""

from gauntlet.envs.repo import Repo, clone, git

from gauntlet.harness.build import env_fingerprint
from gauntlet.harness.cli import main
from gauntlet.harness.schema import HarnessTask, PRInfo

from .fakerelease import _git, make_release_repo

TASK = HarnessTask(
    instance_id="o__r-7",
    repo="https://github.com/o/r",
    pr=PRInfo(repo="o/r", number=7, title="t", url="https://github.com/o/r/pull/7", merged_at="2026-10-01"),
    base_commit="abc",
    solution_commit="def",
    problem_statement="rows can be short",
    statement_source="issue",
    image="img",
    env_fingerprint="f",
    gold_patch="--- a/x\n+++ b/x\n",
    test_patch="--- a/t\n+++ b/t\n",
    test_files=["tests/test_x.py"],
    f2p=["tests/test_x.py::test_a"],
    n2p=["tests/test_x.py::test_new"],
    p2p=["tests/test_x.py::test_old"],
)


def _tasks(tmp_path, monkeypatch, *, path=None, url=None, base="v0.1.0", drifted=False):
    monkeypatch.setenv("GAUNTLET_CACHE", str(tmp_path / "cache"))
    path = path or make_release_repo(tmp_path)
    base = git(path, "rev-parse", f"{base}^{{commit}}").strip()
    fingerprint, _ = env_fingerprint(Repo(path, str(path), "acme__calc"), base, "3.12")
    if drifted:
        fingerprint = fingerprint[::-1]
    update = {"repo": url or str(path), "base_commit": base, "env_fingerprint": fingerprint}
    task = TASK.model_copy(update=update)
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(task.model_dump_json() + "\n")
    return str(tasks)


def test_a_task_that_still_rebuilds_on_its_fingerprint_passes(tmp_path, monkeypatch, capsys):
    assert main(["check-envs", "--tasks", _tasks(tmp_path, monkeypatch)]) == 0
    assert capsys.readouterr().out.startswith("ok ")


def test_a_task_whose_env_drifted_fails_the_check(tmp_path, monkeypatch, capsys):
    assert main(["check-envs", "--tasks", _tasks(tmp_path, monkeypatch, drifted=True)]) == 1
    assert capsys.readouterr().out.startswith("DRIFT o__r-7")


def test_a_base_commit_no_branch_holds_is_fetched_by_sha(tmp_path, monkeypatch, capsys):
    # cachetools #424's base is on no branch, so a fresh clone doesn't have it. GitHub still
    # hands it out by sha, and this repo does too once it's allowed to
    upstream = make_release_repo(tmp_path / "upstream")
    _git(upstream, "checkout", "-q", "-b", "gone")
    _git(upstream, "commit", "-q", "--allow-empty", "-m", "Only on a branch that gets deleted")
    gone = _git(upstream, "rev-parse", "HEAD").strip()
    _git(upstream, "checkout", "-q", "main")
    _git(upstream, "branch", "-q", "-D", "gone")
    _git(upstream, "config", "uploadpack.allowAnySHA1InWant", "true")
    # a file:// url makes git fetch like it would from GitHub, not copy the object store
    url = upstream.as_uri()
    tasks = _tasks(tmp_path, monkeypatch, path=upstream, url=url, base=gone)
    assert not _has(clone(url), gone)
    assert main(["check-envs", "--tasks", tasks]) == 0
    assert capsys.readouterr().out.startswith("ok ")


def _has(repo: Repo, sha: str) -> bool:
    try:
        git(repo.path, "cat-file", "-e", f"{sha}^{{commit}}")
        return True
    except Exception:
        return False
