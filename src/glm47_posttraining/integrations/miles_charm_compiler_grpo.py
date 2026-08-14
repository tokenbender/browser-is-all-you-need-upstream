"""Miles data/reward bridge for the certified compiler-guided CHARM corpus."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any, Sequence

from glm47_posttraining.aider_polyglot.charm_grpo import (
    DATASET_KIND,
    build_charm_grpo_dataset,
    validate_projected_dataset,
    verify_projected_oracles,
)
from glm47_posttraining.aider_polyglot.harness import run_sandbox_preflight
from glm47_posttraining.integrations.miles_aider_polyglot import (
    run_response_contract_preflight,
)


SANDBOX_IMAGE_ENV = "GLM47_CPP_SANDBOX_IMAGE"


def _resolve_selected_manifest(value: str | Path) -> Path:
    path = Path(value).resolve()
    if path.is_file():
        return path
    candidates = (
        path / "selected-manifest.json",
        path / "selected_manifest.json",
        path / "independent-audit" / "selected-manifest.json",
    )
    matches = [candidate for candidate in candidates if candidate.is_file()]
    if len(matches) != 1:
        raise ValueError(
            "--tasks-dir must be the certified selected-manifest.json or contain exactly one"
        )
    return matches[0]


def _copy_preprojected(source: Path, output: Path, *, force: bool) -> dict[str, Path]:
    validation = validate_projected_dataset(source)
    if output == source or output in source.parents or source in output.parents:
        raise ValueError("runtime data output must be separate from the projected source")
    if output.exists():
        if not force:
            raise FileExistsError(f"{output} exists; pass --force to replace it")
        if output.is_symlink():
            raise ValueError(f"refusing to replace symlink: {output}")
        shutil.rmtree(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.copying-{os.getpid()}"
    if temporary.exists():
        raise FileExistsError(f"stale copy staging path: {temporary}")
    shutil.copytree(source, temporary)
    copied = validate_projected_dataset(temporary)
    if copied != validation:
        shutil.rmtree(temporary)
        raise ValueError("preprojected dataset changed during copy")
    os.replace(temporary, output)
    return {
        "grpo_train": output / "grpo" / "train.jsonl",
        "eval": output / "eval" / "mechanism_monitor.jsonl",
        "train_monitor": output / "eval" / "train_monitor.jsonl",
        "mechanism_matrix": output / "eval" / "mechanism_matrix.json",
        "manifest": output / "manifest.json",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-data")
    build.add_argument("--tasks-dir", required=True)
    build.add_argument("--out", required=True)
    build.add_argument("--train-limit", type=int)
    build.add_argument("--eval-limit", type=int)
    build.add_argument("--profile", default="charm-compiler-guided-3ep")
    build.add_argument("--run-id")
    build.add_argument(
        "--eval-splits",
        default="validation,test",
        help=(
            "compatibility flag from the generic Miles runner; the certified "
            "task-disjoint monitor split remains immutable"
        ),
    )
    build.add_argument("--sort-by-size", action="store_true")
    build.add_argument("--task-split-file")
    build.add_argument("--filter-train-oracle-full-marks", action="store_true")
    build.add_argument("--oracle-workers", "--oracle-filter-workers", type=int, default=1)
    build.add_argument("--oracle-cache-dir")
    build.add_argument("--force", action="store_true")
    validate = subparsers.add_parser("validate-data")
    validate.add_argument("--data-dir", required=True)
    verify = subparsers.add_parser("verify-oracles")
    verify.add_argument("--data-dir", required=True)
    verify.add_argument("--image", default="glm47-aider-polyglot-cpp:latest")
    verify.add_argument("--workers", type=int, default=4)
    verify.add_argument("--receipt")
    subparsers.add_parser("preflight")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "preflight":
        run_response_contract_preflight()
        run_sandbox_preflight(
            image=os.environ.get(SANDBOX_IMAGE_ENV, "glm47-aider-polyglot-cpp:latest")
        )
        print("CHARM_COMPILER_GRPO_SANDBOX_READY")
        return
    if args.command == "validate-data":
        print(json.dumps(validate_projected_dataset(args.data_dir), indent=2, sort_keys=True))
        return
    if args.command == "verify-oracles":
        receipt = verify_projected_oracles(
            args.data_dir, image=args.image, workers=args.workers
        )
        if args.receipt:
            receipt_path = Path(args.receipt)
            if receipt_path.exists():
                raise FileExistsError(f"refusing to overwrite receipt: {receipt_path}")
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(
            json.dumps(
                receipt,
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.task_split_file:
        raise ValueError("the certified twelve-task monitor split is immutable")
    if args.eval_splits != "validation,test":
        raise ValueError("the certified twelve-task monitor split cannot be changed")
    if args.filter_train_oracle_full_marks:
        raise ValueError("the certified source manifest already binds terminal oracle passes")
    del args.oracle_workers, args.oracle_cache_dir
    source = Path(args.tasks_dir).resolve()
    source_manifest = source / "manifest.json"
    is_preprojected = False
    if source_manifest.is_file():
        value = json.loads(source_manifest.read_text(encoding="utf-8"))
        is_preprojected = isinstance(value, dict) and value.get("kind") == DATASET_KIND
    if is_preprojected:
        if args.train_limit is not None or args.eval_limit is not None:
            raise ValueError("limits cannot change a digest-pinned preprojected corpus")
        paths = _copy_preprojected(source, Path(args.out).resolve(), force=args.force)
    else:
        paths = build_charm_grpo_dataset(
            _resolve_selected_manifest(source),
            args.out,
            profile=args.profile,
            run_id=args.run_id,
            force=args.force,
            train_limit=args.train_limit,
            eval_limit=args.eval_limit,
            sort_by_size=args.sort_by_size,
        )
    validation = validate_projected_dataset(args.out)
    result: dict[str, Any] = {key: str(path) for key, path in paths.items()}
    result["validation"] = validation
    result["dataset_kind"] = DATASET_KIND
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
