"""Comparable, isolated real-coding runs; observations only, never invented scores."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from actron.contracts import Payload, canonical
from actron.worker import Coding, RepositoryWorker, Runner


def evaluate(
    repository: str,
    base: str,
    coding: Coding,
    contexts: dict[str, Payload],
    output: Path,
    *,
    model: str,
    runner: Runner | None = None,
    max_tokens: int = 12000,
    timeout: float = 300,
    max_attempts: int = 2,
) -> Payload:
    """Context is the sole variable; model, scope, base, tests, tools and budgets match.

    Evaluator checks remain outside the checkout and are invoked only after coding.
    Source correctness/clarification quality require human scoring; no automatic proxy.
    """
    output.mkdir(parents=True, exist_ok=False)
    run_id = uuid.uuid4().hex
    report: Payload = {
        "label": "Observed real-model experiment; synthetic single scenario; no aggregate quality claim",
        "model": model,
        "repository": repository,
        "base": base,
        "max_tokens": max_tokens,
        "timeout_seconds": timeout,
        "max_attempts": max_attempts,
        "same_scope": {
            "objective": "Allow project admins to export reports.",
            "checks": ["exports"],
        },
        "variant_order": list(contexts),
        "runs": [],
        "manual_metrics": {"source_path_correctness": None, "useful_clarification": None},
        "limitations": [
            "One scenario; fixed recorded order may have provider-time effects",
            "Golden evaluator runs after coding; it is never model context",
            "Token usage is reported by the configured real coding adapter",
        ],
    }
    (output / "contexts.json").write_text(canonical(contexts))
    evaluator = Path(__file__).resolve().parents[1] / "demo/evaluator/check_acceptance.py"
    for variant, evidence in contexts.items():
        started = time.monotonic()
        worker = RepositoryWorker(
            repository,
            output / variant,
            coding,
            runner=runner,
            max_tokens=max_tokens,
            timeout=timeout,
            max_attempts=max_attempts,
            check_commands={
                "exports": ["python", "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]
            },
        )
        result = worker.run(f"evaluate:{run_id}:{variant}", report["same_scope"], evidence, base)
        acceptance: dict[str, Any] = {"status": "not_run", "reason": "No tested implementation"}
        if result.get("status") == "succeeded":
            # Execute the evaluator inside the same isolated runner by supplying only
            # its code as argv; the file remains outside the worker/model repository.
            active_runner = worker.runner
            observed = active_runner.run(
                Path(result["path"]),
                [
                    "python",
                    "-B",
                    "-c",
                    evaluator.read_text(),
                    "/work" if type(active_runner).__name__ == "DockerRunner" else result["path"],
                ],
                timeout,
            )
            acceptance = {
                "status": "passed" if observed["exit_code"] == 0 else "failed",
                **observed,
            }
        report["runs"].append(
            {
                "variant": variant,
                "elapsed_seconds": time.monotonic() - started,
                "worker": result,
                "acceptance": acceptance,
            }
        )
        (output / "results.json").write_text(json.dumps(report, indent=2))
    return report
