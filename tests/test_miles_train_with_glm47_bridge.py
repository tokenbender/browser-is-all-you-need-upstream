from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from glm47_posttraining.integrations.miles_train_with_glm47_bridge import (
    _install_wandb_generate_id_compat,
)


def _fake_wandb_modules(monkeypatch, *, existing_generate_id=None):
    wandb = ModuleType("wandb")
    wandb.util = SimpleNamespace()
    if existing_generate_id is not None:
        wandb.util.generate_id = existing_generate_id
    sdk = ModuleType("wandb.sdk")
    lib = ModuleType("wandb.sdk.lib")
    runid = ModuleType("wandb.sdk.lib.runid")
    replacement_generate_id = lambda: "compat-id"
    runid.generate_id = replacement_generate_id
    for name, module in {
        "wandb": wandb,
        "wandb.sdk": sdk,
        "wandb.sdk.lib": lib,
        "wandb.sdk.lib.runid": runid,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    return wandb, replacement_generate_id


def test_wandb_generate_id_compat_restores_removed_alias(monkeypatch) -> None:
    wandb, replacement_generate_id = _fake_wandb_modules(monkeypatch)

    _install_wandb_generate_id_compat()

    assert wandb.util.generate_id is replacement_generate_id
    assert wandb.util.generate_id() == "compat-id"


def test_wandb_generate_id_compat_preserves_existing_alias(monkeypatch) -> None:
    existing_generate_id = lambda: "existing-id"
    wandb, _ = _fake_wandb_modules(
        monkeypatch,
        existing_generate_id=existing_generate_id,
    )

    _install_wandb_generate_id_compat()

    assert wandb.util.generate_id is existing_generate_id
    assert wandb.util.generate_id() == "existing-id"
