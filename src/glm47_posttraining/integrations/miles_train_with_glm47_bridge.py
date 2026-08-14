from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

from glm47_posttraining.integrations.miles_glm47_bridge import register_glm47_bridge


def _install_wandb_generate_id_compat() -> None:
    """Restore the W&B run-ID alias expected by the pinned Miles revision."""

    try:
        import wandb
        from wandb.sdk.lib.runid import generate_id
    except ImportError:
        return
    wandb_util = getattr(wandb, "util", None)
    if wandb_util is not None and not callable(getattr(wandb_util, "generate_id", None)):
        wandb_util.generate_id = generate_id


def _train_py_path() -> Path:
    configured = os.environ.get("MILES_TRAIN_PY", "").strip()
    if configured:
        return Path(configured)
    default = Path("/root/miles/train.py")
    if default.exists():
        return default
    return Path.cwd() / "train.py"


def main() -> None:
    train_py = _train_py_path()
    _install_wandb_generate_id_compat()
    register_glm47_bridge()
    sys.argv[0] = str(train_py)
    runpy.run_path(str(train_py), run_name="__main__")


if __name__ == "__main__":
    main()
