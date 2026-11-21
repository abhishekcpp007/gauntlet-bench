# Sample run

A real run folder, cut down from the golden calibration run in `phase3/golden/before`
(77 episodes, 7 tasks, 11 policies). The store tests read it.

What's kept: 8 episodes, two tasks by four policies.

- Tasks: `hukkin__tomli-318` (a Python Live task) and `pytest-dev__pluggy-1.4.0_to_1.5.0` (an LHT task).
- Policies: `oracle`, `noop`, `cheater` and `cheater:monkeypatch`.

What's trimmed, and nothing else:

- `results.jsonl` holds only those 8 lines, each copied byte for byte from the original file.
- `trajectories/` and `rl/` hold only those 8 episodes' files, byte for byte.
- Every `trajectories/<episode>.blobs` folder is dropped. Those hold the tar archives the sandbox
  uploaded, and the trajectory lines only point at them by hash.
- No stdout was cut. The whole folder fits under 400 KB without it.

`trajectory_path` and `rl_path` inside the rows still name the original machine's paths. The
store doesn't trust them, it looks the files up next to `results.jsonl`.

No zoo cheat in the golden run has a finding tied to a step: their findings all come from the
patch. Only the plain `cheater` has step findings, so that's the episode the flagged-step tests use.
