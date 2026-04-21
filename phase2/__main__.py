from __future__ import annotations

import argparse
import json
import logging
import shlex
from pathlib import Path

from phase1.pipeline import build_phase1, load_sdg_graph

from .orchestrator import OrchestratorConfig, run_phase2_orchestration
from .runtime import build_runtime
from .validation import GuardrailConfig


def _parse_cmd(value: str) -> tuple[str, ...]:
    value = value.strip()
    if not value:
        return ()
    return tuple(shlex.split(value))


def _configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Phase 2 topological orchestration with repeated LLM calls"
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
        choices=["mock", "llm"],
        help="Runtime backend for task execution",
    )
    parser.add_argument(
        "--llm-provider",
        default="groq",
        choices=["groq", "ollama"],
        help="LLM provider when runtime=llm",
    )
    parser.add_argument(
        "--llm-model",
        default="",
        help="Model name for the selected LLM provider",
    )
    parser.add_argument(
        "--llm-base-url",
        default="",
        help="Override OpenAI-compatible base URL for provider",
    )
    parser.add_argument(
        "--llm-api-key",
        default="",
        help="Optional API key override (otherwise env is used)",
    )
    parser.add_argument(
        "--llm-timeout",
        default=120,
        type=int,
        help="HTTP timeout in seconds for LLM requests",
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
        help="Compile command for guardrails",
    )
    parser.add_argument(
        "--test-cmd",
        default="",
        help="Test command for guardrails",
    )
    parser.add_argument(
        "--guardrail-timeout",
        default=90,
        type=int,
        help="Guardrail command timeout in seconds",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )

    args = parser.parse_args(argv)
    _configure_logging(args.log_level)

    repo_root = Path(args.repo).resolve()
    sdg_path = Path(args.sdg).resolve()
    output_dir = Path(args.out).resolve()

    if not sdg_path.exists():
        phase1_output = output_dir.parent / "phase1"
        build_phase1(repo_root, phase1_output)
        sdg_path = phase1_output / "sdg_v1.json"

    sdg = load_sdg_graph(sdg_path)

    runtime = build_runtime(
        args.runtime,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model or None,
        llm_base_url=args.llm_base_url or None,
        llm_api_key=args.llm_api_key or None,
        timeout_sec=max(1, int(args.llm_timeout)),
    )

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

    summary = {
        "output_dir": output_dir.as_posix(),
        "runtime": args.runtime,
        "provider": getattr(runtime, "provider", "unknown"),
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
