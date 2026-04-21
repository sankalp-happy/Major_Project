from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from phase1.pipeline import build_phase1, load_sdg_graph

from .orchestrator import OrchestratorConfig, run_phase2_orchestration
from .runtime import build_runtime
from .validation import GuardrailConfig


def _parse_cmd(value: str) -> tuple[str, ...]:
    value = value.strip()
    if not value:
        return ()
    return tuple(token for token in value.split(" ") if token)


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Phase 2 topological orchestration over SDG artifacts"
    )
    parser.add_argument("--repo", default="repo", help="Path to C repository root")
    parser.add_argument(
        "--sdg",
        default="artifacts/phase1/sdg_v1.json",
        help="Path to SDG JSON artifact",
    )
    parser.add_argument(
        "--out",
        default="artifacts/phase2",
        help="Output directory for phase 2 artifacts",
    )
    parser.add_argument(
        "--runtime",
        default="mock",
        choices=["mock", "rlm"],
        help="Runtime backend for recursive task execution",
    )
    parser.add_argument(
        "--rlm-backend",
        default="openai",
        help="Backend type for RLM (e.g. openai, litellm)",
    )
    parser.add_argument(
        "--rlm-model",
        default="qwen3.5:9b",
        help="Model name for RLM (e.g. qwen3.5:9b, llama3.1, gpt-4o)",
    )
    parser.add_argument(
        "--rlm-base-url",
        default="http://127.0.0.1:11434/v1",
        help="Base URL for the RLM backend (use http://localhost:11434/v1 for ollama)",
    )
    parser.add_argument(
        "--max-attempts",
        default=2,
        type=int,
        help="Maximum attempts per task before giving up",
    )
    parser.add_argument(
        "--enable-guardrails",
        action="store_true",
        help="Run compile/test guardrails after each task",
    )
    parser.add_argument(
        "--compile-cmd",
        default="",
        help="Compile command for guardrails, space-separated",
    )
    parser.add_argument(
        "--test-cmd",
        default="",
        help="Test command for guardrails, space-separated",
    )
    parser.add_argument(
        "--guardrail-timeout",
        default=90,
        type=int,
        help="Guardrail command timeout in seconds",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    sdg_path = Path(args.sdg).resolve()
    output_dir = Path(args.out).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(output_dir / "run.log", mode="w", encoding="utf-8")
        ]
    )

    if not sdg_path.exists():
        phase1_output = output_dir.parent / "phase1"
        build_phase1(repo_root, phase1_output)
        sdg_path = phase1_output / "sdg_v1.json"

    sdg = load_sdg_graph(sdg_path)

    runtime_kwargs = {}
    if args.runtime == "rlm":
        runtime_kwargs = {
            "backend": args.rlm_backend,
            "backend_kwargs": {
                "model_name": args.rlm_model,
                "base_url": args.rlm_base_url,
            },
        }

    runtime = build_runtime(args.runtime, **runtime_kwargs, verbose=args.verbose)

    guardrails = GuardrailConfig(
        enabled=bool(args.enable_guardrails),
        compile_cmd=_parse_cmd(args.compile_cmd),
        test_cmd=_parse_cmd(args.test_cmd),
        timeout_sec=max(1, int(args.guardrail_timeout)),
    )

    config = OrchestratorConfig(
        max_attempts_per_task=max(1, int(args.max_attempts)),
        guardrails=guardrails,
    )

    report = run_phase2_orchestration(
        sdg=sdg,
        repo_root=repo_root,
        output_dir=output_dir,
        runtime=runtime,
        config=config,
    )
    print(f"Finished orchestration. Found {report['metrics']['total_tasks']} tasks.")

    summary = {
        "output_dir": output_dir.as_posix(),
        "runtime": args.runtime,
        "batches": report["plan"]["batch_count"],
        "tasks": report["metrics"]["total_tasks"],
        "successful_tasks": report["metrics"]["successful_tasks"],
        "failed_tasks": report["metrics"]["failed_tasks"],
        "open_obligations": report["obligations"]["open_count"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
