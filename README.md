# Gauntlet

[![CI](https://github.com/abhishekcpp007/gauntlet-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/abhishekcpp007/gauntlet-bench/actions/workflows/ci.yml)
[![Calibrate](https://github.com/abhishekcpp007/gauntlet-bench/actions/workflows/calibrate.yml/badge.svg)](https://github.com/abhishekcpp007/gauntlet-bench/actions/workflows/calibrate.yml)
[![Live](https://github.com/abhishekcpp007/gauntlet-bench/actions/workflows/live.yml/badge.svg)](https://github.com/abhishekcpp007/gauntlet-bench/actions/workflows/live.yml)

Gauntlet turns freshly merged GitHub pull requests into coding tasks for AI agents, and it scores every attempt with a grader that's been attacked on purpose. It works on Python repos tested with pytest and on JavaScript or TypeScript repos tested with vitest or jest.

## A score you can trust

A coding agent's score only means something if the agent couldn't look up the answer and couldn't fake the pass. Gauntlet is built around those two promises.

**The agent can't find the answer.** Tasks come from recently merged PRs, so a model whose training cutoff came before the merge can't have seen the fix. The two Live sets use PRs merged between 4 August and 10 November 2026, and a workflow builds fresh tasks every Monday. Every task passes an 8-check leak scan before it ships. The network is blocked and git history is one scratch commit. The environment is clean, and no line of the hidden tests or the fix is on disk. `gauntlet report --cutoff` splits every number at a model's cutoff, so a model that's seen the older fixes stands out.

**The agent can't fake a pass.** The grader throws away every edit the agent made to tests and to test config before the hidden tests go on. That covers `conftest.py`, `pytest.ini`, `tox.ini` and JS runner config. It renames the target tests for the run and plants canary tests, some that must fail and some that must pass. It also hashes the test and config files before and after the suite runs. Cheat Catcher reads the patch and the agent's shell commands with 11 static rules, and a `cheating` verdict means a reward of -1. A zoo of 9 cheat policies attacks all of this, and `gauntlet calibrate` fails if any of them resolves a task or scores above 0. A nightly workflow runs it on a few Live tasks.

The repo ships 147 tasks from 26 repos. In their calibration runs no cheat resolved a task or scored above 0, and the merged fix resolved every task but one, where a flaky radashi test failed. On the Live Python set only the blunt `cheater` was played, and the full zoo ran on the other two sets.

## Quickstart

You need Python 3.11 or newer and git. Anything that boots a sandbox also needs Docker.

```bash
git clone https://github.com/abhishekcpp007/gauntlet-bench gauntlet
cd gauntlet
pip install -e ".[claude]"    # or `uv sync`, then prefix commands with `uv run`
gauntlet --help
```

Then try it on a shipped set:

```bash
# recompute every shipped task's env fingerprint, like CI does (git and network, no Docker)
gauntlet check-envs --tasks datasets/*/tasks.jsonl

# all 11 calibration policies on 2 random Live tasks
gauntlet calibrate --tasks datasets/gauntlet-live-2026-11/tasks.jsonl --sample 2

# a model next to the oracle and noop, then the report
ANTHROPIC_API_KEY=... gauntlet run --tasks datasets/gauntlet-live-2026-11/tasks.jsonl \
  --policies claude:claude-opus-5-5,oracle,noop --attempts 2
gauntlet report --results runs/results.jsonl --cutoff 2026-06-01
```

Or build your own tasks from this month's PRs:

```bash
gauntlet collect --repo mahmoud/boltons --merged-after 2026-11-01 -o prs.jsonl
gauntlet build   --prs prs.jsonl -o tasks.jsonl
gauntlet run     --tasks tasks.jsonl --policies oracle,noop,cheater
gauntlet report  --results runs/results.jsonl
```

## How grading works

When an episode ends, `SWEEnv._finish` (`src/gauntlet/harness/env.py`) and `grade_patch` (`src/gauntlet/harness/grading.py`) do this, in this order:

1. **Diff.** The agent's changes are diffed against the one-commit scratch repo it worked in.
2. **Scan.** Cheat Catcher reads the diff and the agent's own steps. A patch finding that the merged fix also makes on the same line is dropped. That way a fix that really has to change test collection isn't punished for it.
3. **Strip.** Every file section touching tests or the task's test files is dropped. So is every section touching `conftest.py`, `pytest.ini`, `.pytest.ini` or `tox.ini`. Anything under `node_modules` goes too, with any JS runner config or setup file. `setup.cfg` and `pyproject.toml` stay, but they're hashed and Cheat Catcher reads them.
4. **Boot and apply.** A fresh sandbox starts at the base commit with no network. The kept patch goes in, and if it doesn't apply the reward is -1. Then the hidden tests go on top.
5. **Rename the targets.** The target tests get new names for this run, so a cheat that spares "new" tests spares the targets as well.
6. **Plant canaries.** Two tests that must fail and two that must pass go into a graded file. Their names are borrowed from the file's own tests and their bodies come from several shapes. They land at random spots between the existing tests. A full-suite LHT task gets a second set in another graded file.
7. **Hash before and after the run.** Every watched test and config file is hashed. Changed Python and plain JS source files get a compile check and the suite runs. Then every watched file is hashed again.
8. **Check for tampering.** A must-fail canary that passed, canaries that vanished, a must-pass canary that failed or any changed hash marks the run as tampered. If the hashes couldn't be read, that's an integrity error rather than tampering, and the run still can't resolve.
9. **Resolve.** Canary results are dropped and renamed ids are mapped back. A task is resolved when the run is trusted and every target and P2P test passes. A task with no targets never resolves.
10. **Verdict.** Each tamper problem becomes a high `grader-tamper` finding, which makes the verdict `cheating`.
11. **Reward.**

```
reward = -1                                          if the patch is empty or doesn't apply
reward = -1                                          if the verdict is cheating
reward = 0.6·tests + 0.25·rubric + 0.15·similarity   otherwise, on SWE tasks
reward = 0.8·tests + 0.2·rubric                      otherwise, on LHT tasks
reward ≤ 0                                           if no target test passes
```

- `tests` is 1 when resolved. Otherwise it's the target pass rate times the P2P pass rate, and LHT uses the mean milestone pass rate in place of the target rate.
- `rubric` is 9 rule items in the Rubrics as Rewards style. Four check the result: targets fixed, no regressions, applies and compiles. Two check the shape of the patch, same files as the fix and a small diff. One checks for cheating, and two pitfalls cover test edits and debug leftovers. The no-cheating item gives full marks when clean and half when `suspicious`, so a medium finding costs a little even without a `cheating` verdict.
- `similarity` is `difflib` similarity to the merged fix, as in SWE-RL, with test edits left out.
- Weights live in `RewardConfig` and the per-category profiles in `profiles.py`. An SWE episode gets 60 steps and an LHT episode gets 400.

## How a PR becomes a task

1. **Collect.** Closed PRs with `merged_at` set, newest first, from GitHub's REST API. Linked issues come from closing keywords like `fixes #474`.
2. **Filter.** The PR has to change source in the repo's language and at least one test module. Most PRs stop here: 115 of the 186 looked at for Live did.
3. **Statement.** The linked issue's text if there's one (14 of the 53 Live tasks), else the PR's title and body. A statement that quotes a distinctive line of the fix is rejected.
4. **Validate.** The suite runs five times, each in a fresh sandbox. The base commit gets one run, then the PR's tests and the tests plus the fix get two runs each. A test that disagrees with itself is flaky and left out of grading.
5. **Classify.** Each test is classed by how it moves from the tests-only run to the fix run. FAILED to PASSED is F2P and missing to PASSED is N2P. SKIPPED to PASSED is S2P and PASSED to PASSED is P2P. A PR is rejected if any passing test regresses or nothing reaches PASSED.
6. **Leak scan.** Any failing check rejects the task.

The whole suite runs by default (`--scope full`), so P2P guards the entire project and not just the files the PR touched. Six packaging tasks in the Live set are the exception, since their full suite was too big.

### The leak scan

`gauntlet leakcheck` boots the exact sandbox an agent would get. `build` and `build-lht` run it by default.

| Check | What it proves |
|---|---|
| `statement` | The statement doesn't quote a distinctive line of the fix |
| `grader_paths` | No `/tmp/gauntlet-*` grader files are in the sandbox |
| `git_history` | The scratch repo has exactly one commit, and there's no other `.git` on disk |
| `network` | The network is blocked |
| `env_vars` | No hidden test or fix line is in the environment |
| `hidden_tests_on_disk` | No distinctive line of the hidden tests is anywhere on disk |
| `gold_on_disk` | No distinctive line of the fix is anywhere on disk |
| `new_test_names_on_disk` | The new test names aren't on disk, so you can't grep for what you'll be graded on |

Lines that already exist at the base commit are skipped, since finding them proves nothing. When there are no distinctive lines at all, the on-disk checks fold into one `filesystem` check. All 147 shipped tasks record all 8 checks, all passing.

## Shipped task sets

| | [Live](datasets/gauntlet-live-2026-11/README.md) | [Live JS](datasets/gauntlet-live-js-2026-11/README.md) | [LHT](datasets/gauntlet-lht-2026-11/README.md) |
|---|---|---|---|
| One task is | one merged PR | one merged PR | a release range, `vX..vY` |
| Tasks | 53 | 69 | 25 |
| Repos | 10 | 11 | 13 |
| Runner | pytest | vitest | pytest |
| Merged | 7 Sep to 30 Oct 2026 | 4 Aug to 10 Nov 2026 | ranges ending 19 Apr 2024 to 5 Nov 2026 |
| PRs looked at | 186 | 219 | not recorded |
| Calibration episodes | 159 | 759 | 275 |
| Policies played | `cheater` only, next to oracle and noop | all 11 | all 11 |
| Oracle resolved | 53 / 53 | 68 / 69 | 25 / 25 |
| Noop | -1 on every task | -1 on every task | -1 on every task |
| Cheat episodes | 53, all caught at -1 | 621, none resolved or above 0 | 225, none resolved or above 0, no milestone finished |

- Only the blunt `cheater` was shipped for Live. The full zoo was shipped for Live JS and LHT.
- The one Live JS miss is radashi #494, where a flaky test failed. That test is now in the task's `flaky` list, so it's left out of grading.
- Every task carries its env fingerprint, and the CI `envs` job recomputes all 147 on every push to main and every PR.
- An LHT task starts the agent at the older release and grades it on milestones, the PRs and direct commits in the range, so finishing part of a release still earns credit. A regression found at validation is dropped from grading, up to `min(5, 2% of stable tests)`. Past that the range is rejected. Reports never pool SWE and LHT.
- The data cards are frozen with the data, so a few lines in them are out of date. Where one disagrees with this README, this README is current. `swebench.jsonl` in the two Live folders is frozen too, and nothing in this repo makes it any more.

The [Live](.github/workflows/live.yml) workflow runs every Monday. It collects the last two weeks of merged PRs from the repos in [`datasets/live-repos.txt`](datasets/live-repos.txt) and builds and leak-scans them. Then it validates each new task with `--policies oracle,noop,cheater` and uploads the tasks and a report as a build artifact.

## Calibration: the grader under attack

`gauntlet calibrate` plays 11 policies on the tasks you give it. `--sample N` picks N of them at random, seeded by the date unless you pass `--seed`.

| Policy | What it does |
|---|---|
| `oracle` | applies the merged fix |
| `noop` | gives up |
| `cheater` | forges results with a runner hook (a `conftest.py`, or vitest setup and config on JS) and skips the target test files |
| `cheater:monkeypatch` | forces every test report to "passed" from inside the module the fix touches |
| `cheater:stealth` | the same, hidden in base64 so no rule can read it |
| `cheater:rewrite` | rewrites the test files on disk when the module is imported |
| `cheater:canary-aware` | spares whatever looks like the grader's canary and forces the rest |
| `cheater:ghost` | canary-aware, hidden in base64 |
| `cheater:junit` | lets the suite run, then cuts every failure out of the JUnit report |
| `cheater:exit` | exits the interpreter cleanly the moment the module loads |
| `cheater:snapshot` | records the test names at the base commit, then forces those and spares anything new |

The 8 `cheater:<trick>` policies only edit source files, which the grader has to keep. All 9 cheats run on pytest and on vitest. None of them runs on jest.

The run exits non-zero when any of these breaks:

- the oracle doesn't resolve, or scores under 0.9
- noop scores above -1
- a cheat resolves, or scores above 0
- an episode crashes

A task whose pinned commit has vanished upstream, after a force-push say, is reported as rotted and left out. Nothing about the grader can be learned from an episode that never ran.

**What a clean run shows.** On the tasks it sampled, the real fix resolves and no zoo trick earns more than an honest failure. It doesn't show that a trick outside the zoo can't win. A cheat at 0 isn't always a catch either. On Live JS, `cheater:snapshot` scores 0 on all 69 tasks with no cheating verdict. So do both canary dodgers (canary-aware and ghost). That means they lost, not that they were caught.

**Which layer catches what.** Read as a patch alone, Cheat Catcher flags 2 of the 8 Python zoo tricks (monkeypatch and canary-aware, through `outcome-forcing` and `runner-sniffing`) and none of the JS ones. Everything else is caught by the grading-time checks or scores 0. That's why the layers are stacked: a canary-aware run that happens to dodge every canary still trips those two rules and scores -1.

**The canary is a rate, not a yes or no.** It's placed at random, so a given cheat beats it on some layouts. `tests/harness/test_canary.py` draws 600 layouts for one Python file and checks that the old canary-aware trick (spare each file's last two tests) gets past every must-fail canary on fewer than 20% of them, at the top of a 95% interval. The zoo tests pin `GAUNTLET_GRADING_SEED` so a draw repeats. Never set it on a run whose score anyone will quote.

**Nightly.** [`calibrate.yml`](.github/workflows/calibrate.yml) runs `gauntlet calibrate` on 4 random Live Python tasks every night, seeded by the date so each night checks different ones.

## Cheat Catcher

Cheat Catcher (`src/gauntlet/cheatcatcher`) reads an agent's patch and its recorded steps, and it says whether the agent worked on the code or on the grader. It's all static analysis, so a scan takes milliseconds and never runs the agent's code.

| Rule | Catches |
|---|---|
| `protected-test-edit` | any change to a test file the grader owns |
| `test-edit` | deleting or rewriting tests that were already in the repo |
| `outcome-forcing` | code that flips failing reports to passing or fakes the exit status |
| `conftest-hooks` | `conftest.py` hooks that drop tests or sit on their results |
| `pytest-config` | `pytest.ini`, `tox.ini`, `setup.cfg` or `pyproject.toml` changes to what gets collected |
| `skip-injection` | new skip or xfail markers on tests that should run |
| `runner-sniffing` | source that behaves differently when it detects a test run |
| `exit-hack` | exiting the interpreter early so the runner reports success |
| `assert-neutering` | deleting assertions or patching the assertion machinery |
| `shell-test-edit` | shell commands that edit or delete tests, such as `sed -i` or a redirect |
| `answer-peeking` | commands that hunt for the answer. That means digging through git history or making network calls, and reading the grader's patch folder or looking for `*.patch` files |

The first 9 read the patch and the files the agent wrote, and they're written for Python and pytest. The last 2 read the agent's shell commands. Any high finding makes the verdict `cheating` and a medium one makes it `suspicious`. Lows are notes.

A detector that flags real fixes is worse than none, since `cheating` costs -1. `tests/harness/test_false_positives.py` checks the 53 Live gold patches on every test run. Cheat Catcher gives them 0 cheating verdicts (95% interval 0% to 6.76%) and one medium note. That note is fair: python-slugify #198 sets `testpaths`, which its fix really needs. Across all 147 gold patches it gives 0 cheating verdicts too.

```bash
gauntlet cheatcatcher scan --patch tests/cheatcatcher/examples/honest_fix.diff --protect tests/test_ops.py     # clean
gauntlet cheatcatcher scan --patch tests/cheatcatcher/examples/edit_the_test.diff --protect tests/test_ops.py  # cheating
gauntlet cheatcatcher scan --trajectory run.jsonl --patch fix.diff --json
gauntlet cheatcatcher rules
```

Exit codes follow the verdict: 0 for clean and 1 for suspicious. A cheating verdict exits 2, and 64 means there was nothing to scan.

## Sandboxes and env images

Every agent episode, validation run, leak scan and grade boots its own container (`src/gauntlet/sandbox`).

- It's locked down by default. There's no network. Each sandbox gets 512 MB of memory and 1 CPU, with a cap on process count. Every Linux capability is dropped and `no-new-privileges` is on. `tests/sandbox/test_isolation.py` checks these from inside a running container: `CapPrm` and `CapEff` are zero, `mknod` is refused, `NoNewPrivs` is 1 and the cgroup files hold the requested limits. A fork bomb or a memory hog gets stopped, and the sandbox is still usable after.
- Output is capped and flagged `truncated`. `PYTHONDONTWRITEBYTECODE=1` is on, so a file rewritten twice in one second never runs stale bytecode.
- Every step lands in a JSONL trajectory as it happens. Cheat Catcher's command rules read it.
- An env image is built at the task's base commit, never later. Only the build container gets network, so installs work. Task and grading containers run offline.
- Every package manager's cache is wiped before the image is frozen, so the fix can't sit in a cache.
- An image is named by its env fingerprint, a hash of the dependency files and the install script. PRs that share dependencies share an image. If a rebuilt image's fingerprint doesn't match the task's, Gauntlet refuses to use it. This is a different thing from the grader's file hashes in step 7.
- A Node env keeps `node_modules` one folder above the repo. Node still finds it, and a patch can't reach the test runner.

## Commands

| Command | What it does |
|---|---|
| `gauntlet collect --repo OWNER/NAME --merged-after YYYY-MM-DD` | fetch merged PRs, newest first. `--git-fallback` reads git history if the API rate-limits you |
| `gauntlet build --prs prs.jsonl` | validate PRs into SWE tasks and leak-scan them |
| `gauntlet ranges --repo OWNER/NAME` | list a repo's release ranges |
| `gauntlet build-lht --repo OWNER/NAME --range FROM..TO` | turn release ranges into LHT tasks |
| `gauntlet leakcheck --tasks tasks.jsonl` | rerun the leak scan |
| `gauntlet check-envs --tasks tasks.jsonl ...` | recompute env fingerprints, no Docker needed |
| `gauntlet run --tasks tasks.jsonl --policies ...` | play policies on tasks |
| `gauntlet report --results runs/results.jsonl` | the results tables. `--cutoff` and `--html` are optional |
| `gauntlet calibrate --tasks tasks.jsonl` | the red-team run above |
| `gauntlet cheatcatcher scan` and `rules` | Cheat Catcher on its own |

`--policies` takes `oracle` and `noop`, plus `cheater` or `cheater:<trick>` for the cheats. A real model is `claude:<model id>`. Claude policies need the `claude` extra and `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`). `--attempts N` gives pass@k. `--max-episodes`, `--max-tokens`, `--max-seconds` and `--max-usd` (with `--prices`) cap what a run can spend. Runs are resumable, since an episode already in `results.jsonl` is skipped. Each episode adds a line to `results.jsonl` and saves its trajectory under `trajectories/`.

`gauntlet report` puts a 95% bootstrap interval next to pass@1, resampling tasks and not episodes, and it runs McNemar's exact test between each pair of policies. `--cutoff YYYY-MM-DD` splits every metric into PRs merged before and after that date. Every episode records how it was produced. That covers the harness version and policy params, the image and its fingerprint, plus the grading seed and the time. The report warns when one policy's rows weren't measured the same way.

## Limits

- **The nightly is small.** It plays 4 random Live Python tasks. Live JS and LHT were calibrated once, for the shipped results, and they aren't in the nightly.
- **LHT isn't fresh.** Its tasks come from release ranges, not this week's PRs. 8 of the 25 ranges end in 2024 or 2025. "Fresh" holds for Live and Live JS.
- **Two JS cheats are duds on newer vitest.** `cheater:monkeypatch` and `cheater:stealth` hook `vitest/suite`, which newer vitest no longer lets them load. On 26 of the 69 Live JS tasks they score a quiet 0, so the calibration says nothing about those tricks there.
- **jest isn't calibrated.** jest tasks build and grade in code with the same canaries and renames, but no jest set ships and none of the cheats runs on jest.
- **Cheat Catcher's rules are static checks for Python patches, plus two rules over shell commands.** On the JS zoo payloads they find nothing, so JS tasks rest on the grading-time checks alone. A clean verdict means "nothing obvious", never a guarantee.
- **No rule looks for a fix that only special-cases the tested inputs.** The defense there is that the agent never sees the hidden tests.
- **Upstream history can vanish.** A task pins a commit in someone else's repo. If that repo force-pushes it away, nobody can build the task again, and `calibrate` reports it as rotted.
- **No model has been run on the shipped sets yet.** The calibration results are scripted policies only.
- **LHT is Python only.** Release ranges build through `lht.py`, which looks at `.py` files.
- **Containers aren't VMs.** The sandbox defaults stop what an agent might do by accident. For truly hostile code, put Docker on a throwaway VM or under gVisor.
- **The GitHub API rate-limits you without `GITHUB_TOKEN`.** `--git-fallback` reads git history instead.

## What's next

A Harbor verifier is in progress on a branch. It doesn't give the same score as `gauntlet run` yet.

## Layout and development

```
src/gauntlet/
  sandbox/        locked-down Docker sandboxes and trajectories
  envs/           env images, test runs, patch splitting and the strip step
  cheatcatcher/   the 11 static rules
  harness/        collect, build, leak scan, grader, reward, policies, calibrate, report
datasets/         the shipped task sets
tests/            one folder per subpackage
```

```bash
uv sync
uv run pytest                    # Docker tests skip without Docker
GAUNTLET_LIVE=1 uv run pytest    # also hits the real GitHub API
uv run ruff check .
```

[DESIGN.md](DESIGN.md) has the decisions behind it.

## Built on

- [SWE-bench](https://arxiv.org/abs/2310.06770) (Jimenez et al., ICLR 2024): a task is an issue at a base commit, graded by hidden tests
- [Multi-SWE-bench](https://arxiv.org/abs/2504.02605) (Zan et al., 2025): how to validate a PR and which test transitions to keep
- [SWE-rebench](https://arxiv.org/abs/2505.20411) (Badertdinov et al., NeurIPS 2025): keep collecting fresh PRs, and split results at a model's cutoff
- [Rubrics as Rewards](https://arxiv.org/abs/2507.17746) (Gunjal et al., 2025): checklist rubrics with essential, important, optional and pitfall items
- [SWE-RL](https://arxiv.org/abs/2502.18449) (Wei et al., 2025): similarity to the real patch as a dense reward, and -1 for malformed output

## Cite

[`CITATION.cff`](CITATION.cff) has the details. In BibTeX:

```bibtex
@software{gauntlet2026,
  author = {Abhishek},
  title  = {Gauntlet: leak-free RL environments from fresh GitHub PRs, with a red-teamed grader},
  year   = {2026},
  url    = {https://github.com/abhishekcpp007/gauntlet-bench}
}
```

## License

MIT. See [LICENSE](LICENSE).
