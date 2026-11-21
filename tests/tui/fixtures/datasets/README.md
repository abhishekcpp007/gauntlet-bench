# Sample datasets

Two tiny datasets, made of real rows copied byte for byte from `datasets/`. The store tests read
them so they don't depend on the repo's real datasets folder.

`gauntlet-mini-live`

- `tasks.jsonl`: `hukkin__tomli-318` from the Live set (written before `category` and `runner`
  existed, so it loads as swe and pytest) and `unjs__confbox-103` from the Live JS set.
- `validation.jsonl`: slim rows. The 3 for tomli from Live, then the oracle, noop and cheater rows
  for confbox from Live JS, which also carry `tampered`.
- `stats.json`: the Live set's own file, unchanged, so its numbers describe all 53 Live tasks.

`gauntlet-mini-lht`

- `tasks.jsonl`: `pytest-dev__pluggy-1.4.0_to_1.5.0` and `un33k__python-slugify-v9.1.0_to_v9.1.1`
  from the LHT set.
- `validation.jsonl`: full `EpisodeResult` rows. The oracle, noop and cheater rows for pluggy and
  the `cheater:exit` row for slugify.
