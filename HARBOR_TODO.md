# Harbor: what this branch doesn't do yet

This branch ports old gauntlet-harness PR #1 (`harbor-format`). `gauntlet export --format harbor` writes one Harbor task folder per task, and `gauntlet harbor-grade` grades the agent's patch inside Harbor's verifier with Gauntlet's own grader code.

**A Harbor score from this branch is not yet the same as a Gauntlet score.** Four known gaps are listed below. None of them is fixed here. Each one changes Harbor rewards or Harbor trust only. None of the fixes would move a `gauntlet run` score, since they all live in `src/gauntlet/harness/harbor.py`.

Line numbers are for this branch. "Harbor" means Harbor's own source, read from a local checkout of Harbor 0.25.0.

## 1. The rule rubric is dropped, so the reward differs

- `grade_here` calls `compute_reward(grade, None, ...)`, so `rubric=None` (`harbor.py:328-330`).
- `gauntlet run` always scores the rule rubric, judge or no judge. `SWEEnv` uses `task.rubric or default_rubric(task)` and `score_rubric` (`env.py:325-331`). `default_rubric` says "Rule-only rubric. Always available, needs no model" (`rubric.py:217-218`). Judge items are just skipped when there's no client (`rubric.py:337`).
- With `None`, `compute_reward` spreads the rubric's weight over tests and similarity (`reward.py:90-96`).
- Worked numbers. A resolved SWE task with similarity 0.4 and rule rubric 0.8 scores 0.86 in `gauntlet run` and 0.88 in Harbor. An LHT task with P2P intact scores 0.58 in `gauntlet run` and 0.5 in Harbor, at milestone mean 0.5 and rubric 0.9.
- Outside the short cuts (a malformed or cheating patch gives -1, `reward.py:58-63`) and the no-progress cap of 0 (`reward.py:101-104`), the two only match by chance.
- The docstring's reason, "the verifier runs offline" (`harbor.py:309-310`), doesn't hold. The rule rubric needs no model.
- Likely fix: score the rule rubric in `grade_here` the way `SWEEnv` does, about 4 lines.

## 2. Cheat Catcher runs 9 of its 11 rules

- `grade_here` calls `scan_beyond_gold(None, patch, task)`, with no trajectory (`harbor.py:322`).
- `shell-test-edit` and `answer-peeking` only look at `ctx.commands` (`cheatcatcher/rules.py:309, 345`). Only `from_trajectory` fills that list (`cheatcatcher/context.py:169-181`). `from_patch` (`:223`) only adds file changes.
- So a test file edited with `sed` or a `grep` for the gold patch isn't seen in Harbor. The patch rules and the grader's runtime tamper checks still run.
- No fix is planned yet. It needs the agent's commands from Harbor's side, and Harbor's trajectory isn't Gauntlet's.

## 3. The grader shares a container and a user with the agent's code

- The agent never touches the verifier container. `environment_mode = "separate"` (`harbor.py:124`) gives the verifier a fresh one, and only `/logs/artifacts` is carried across.
- But the test suite runs the agent's patched code, and it runs next to the grader. `LocalSandbox.exec` is a plain `subprocess.run(["sh", "-c", ...])` in the verifier container, as the grader's own user (`harbor.py:240-303`, the call at `:268`). In `gauntlet run` the grader sits on the host and reaches the sandbox only through Docker (`sandbox/sandbox.py:224`).
- `/tests/task.json` holds the whole task, gold patch included. It's written at export (`harbor.py:233`) and read by `harbor_grade` (`:346`). Nothing deletes it, so it's on disk while the suite imports the agent's code. A source edit that reads it and applies `gold_patch` at import would make the real tests pass for real. Neither the canaries nor the file hashes would trip, and no patch rule looks for it.
- `/logs/verifier/reward.json` is writable by that same code. Harbor reads it after `test.sh` returns and never checks the exit status (Harbor `verifier/verifier.py:269-272, 299-310`). Code run by the suite could write the file and kill the grader, or overwrite it later from a background process.
- Both come from reading code. Neither has been tried. They're on the Phase 3 red-team list.
- Likely fixes: delete `/tests` right after reading task.json, about 2 lines. After the suite, kill every other process in the container and write the reward last. Have `test.sh` write 0 when `harbor-grade` exits non-zero. That's about 15 lines.

## 4. The env is rebuilt and nothing checks its fingerprint

- The Harbor Dockerfile starts from the base image and runs the task's install script again (`harbor.py:145-179`, install.sh written at `:224`). The install lines are unpinned `pip install` (`envs/detect.py:314-336`), so versions resolve when Harbor builds the image.
- The task's `env_fingerprint` is copied into task.toml's metadata (`harbor.py:117`) and never compared with anything.
- `gauntlet run` grades on the image the task was validated in when it's there. When it has to rebuild, it refuses an image whose fingerprint drifted (`sandboxing.py:83-87`).
- So a Harbor run can grade on an env the task was never validated in, and nothing says so.
- Likely fix: recompute the fingerprint at export with `build.env_fingerprint` and refuse on a mismatch, about 5 lines. That catches a changed install script or changed dependency files. Package versions resolved at build time would still float.

## Smaller differences in the verifier

These come from the same code reading. They're smaller, but they're still not what `gauntlet run` does.

- On a timeout, `LocalSandbox` kills `sh` only, so pytest or vitest workers under it can keep running. The Docker sandbox kills the whole process group.
- `PYTHONDONTWRITEBYTECODE=1` isn't set, where every Docker sandbox sets it.
- If reinstall prints `REINSTALL_FAILED`, `grade_here` raises and the reward is 0 for any patch, oracle included. `gauntlet run` records it and grades on.
- The grader's own third-party deps aren't locked, since `uv pip install` doesn't read `uv.lock`. `--grader-ref` does pin all first-party code now, since it's one repo.

## Not checked on this branch

- No Docker and no Harbor run. The 11 tests in `tests/harness/test_harbor.py` pass offline, but none of them builds an image or starts Harbor.
- The verifier installs the grader from `git+https://github.com/abhishekcpp007/NEW_REPO@<ref>`. Until the new repo is on GitHub under its real name, no Harbor image can be built from this branch and `harbor.yml` can't pass.
- Harbor's `no-network` mode needs nftables fib inet on the Docker host. Docker Desktop on a Mac may not have it, so a real run needs a Linux host.
- No parity run yet. Grading the same patches (gold, empty, a partial fix, a zoo cheat) with `grade_patch` and with Harbor's verifier is one of the Phase 3 checks.
