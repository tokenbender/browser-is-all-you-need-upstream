





from __future__ import annotations

import os
import sys
from pathlib import Path

from glm47_posttraining.integrations.miles_glm47_bridge import register_glm47_bridge

PP_OVERRIDE_MARKER = "if args.pipeline_model_parallel_size == 1 and world_size > 1:"
PP_OVERRIDE_REPLACEMENT = (
    "if False:  # keep requested PP1 during conversion"
)


def _convert_py_path() -> Path:
    configured = os.environ.get("MILES_CONVERT_PY", "").strip()
    if configured:
        return Path(configured)
    default = Path("/root/miles/tools/convert_hf_to_torch_dist.py")
    if default.exists():
        return default
    return Path.cwd() / "tools" / "convert_hf_to_torch_dist.py"


def _load_source(convert_py: Path) -> str:
    source = convert_py.read_text(encoding="utf-8")
    if os.environ.get("GLM47_KEEP_PP1", "0") != "1":
        return source
    if PP_OVERRIDE_MARKER not in source:
        raise RuntimeError(
            f"GLM47_KEEP_PP1=1 but the PP-override marker is missing in {convert_py}; "
            "inspect the converter before forcing PP1"
        )
    return source.replace(PP_OVERRIDE_MARKER, PP_OVERRIDE_REPLACEMENT, 1)


def main() -> None:
    convert_py = _convert_py_path()
    register_glm47_bridge()
    source = _load_source(convert_py)
    sys.argv[0] = str(convert_py)
    globals_ns = {"__name__": "__main__", "__file__": str(convert_py), "__builtins__": __builtins__}
    exec(compile(source, str(convert_py), "exec"), globals_ns)


if __name__ == "__main__":
    main()
