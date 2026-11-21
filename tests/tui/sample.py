"""The store's sample data: a trimmed real run and two tiny datasets. See fixtures/*/README.md."""

from __future__ import annotations

from pathlib import Path

from gauntlet.tui.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_RUN = FIXTURES / "sample-run"
SAMPLE_DATASETS = FIXTURES / "datasets"
REPO_DATASETS = Path(__file__).resolve().parents[2] / "datasets"

RUN_ID = "sample-run"
LIVE_ID = "mini-live"
LHT_ID = "mini-lht"
SHIPPED_LIVE = "shipped-mini-live"
SHIPPED_LHT = "shipped-mini-lht"

TOMLI = "hukkin__tomli-318"
CONFBOX = "unjs__confbox-103"
PLUGGY = "pytest-dev__pluggy-1.4.0_to_1.5.0"
SLUGIFY_LHT = "un33k__python-slugify-v9.1.0_to_v9.1.1"
TOMLI_CHEATER = f"{TOMLI}__cheater__0"
TOMLI_ORACLE = f"{TOMLI}__oracle__0"
PLUGGY_CHEATER = f"{PLUGGY}__cheater__0"
PLUGGY_MONKEYPATCH = f"{PLUGGY}__cheater-monkeypatch__0"


def sample_store() -> Store:
    return Store.load(SAMPLE_DATASETS, [SAMPLE_RUN])
