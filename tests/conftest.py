"""Shared fixtures: tiny synthetic worlds written to a temporary folder."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.generator.generate import DEFAULT_ERRORS, DEFAULT_TRAPS, GeneratorConfig, generate  # noqa: E402
from src.generator.writers import write_world  # noqa: E402
from src.reconciliation import engine  # noqa: E402


def small_config(errors=None, traps=None, **kw) -> GeneratorConfig:
    base = dict(seed=11, n_restaurants=10, mean_orders_per_day=9.0, n_plan_changes=4, n_similar_name_pairs=2,
                n_duplicate_export_rows=3, refund_hidden_owner_share=0.0, refund_not_deducted_hidden=0,
                errors={k: 0 for k in DEFAULT_ERRORS}, traps={k: 0 for k in DEFAULT_TRAPS})
    base.update(kw)
    cfg = GeneratorConfig(**base)
    cfg.errors.update(errors or {})
    cfg.traps.update(traps or {})
    return cfg


@pytest.fixture
def run_world(tmp_path):
    def _run(cfg: GeneratorConfig):
        world = generate(cfg)
        raw = tmp_path / "raw"
        write_world(world, raw, tmp_path / "answer")
        result = engine.run(raw_dir=raw, interim_dir=tmp_path / "interim", ai_mode="off")
        return world, result
    return _run
