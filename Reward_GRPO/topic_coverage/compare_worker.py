"""Credential-free subprocess entry point for the unmodified generalized reward."""

import json
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(root), str(root / "src")]
    from Reward_GRPO.generalized_cpp_grpo import TaskRegistry, score_sample

    request, output, registry = (Path(value) for value in sys.argv[1:])
    result = score_sample(
        json.loads(request.read_text(encoding="utf-8")), registry=TaskRegistry(registry)
    )
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, sort_keys=True, allow_nan=False)
        handle.write("\n")


if __name__ == "__main__":
    main()
