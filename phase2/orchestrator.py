from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from .context import build_function_context_package
from .metrics import MetricsCollector
from .planner import MigrationPlan, plan_migration_batches, serialize_migration_plan
from .runtime import Runtime, RuntimeTaskRequest
from .validation import GuardrailConfig, run_guardrails


@dataclass(frozen=True)
class OrchestratorConfig:
    max_attempts_per_task: int = 2
    guardrails: GuardrailConfig = field(default_factory=GuardrailConfig)


LOGGER = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n")


def _function_name_lookup(sdg: nx.MultiDiGraph) -> dict[str, str]:
    return {
        node_id: attrs.get("name", node_id)
        for node_id, attrs in sdg.nodes(data=True)
        if attrs.get("node_type") == "Function"
    }


def _flatten_plan(plan: MigrationPlan) -> list[tuple[int, str]]:
    execution_units: list[tuple[int, str]] = []
    for batch in plan.batches:
        for function_node_id in batch.function_node_ids:
            execution_units.append((batch.index, function_node_id))
    return execution_units


def run_phase2_orchestration(
    *,
    sdg: nx.MultiDiGraph,
    repo_root: Path,
    output_dir: Path,
    runtime: Runtime,
    config: OrchestratorConfig,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    plan = plan_migration_batches(sdg)
    name_by_id = _function_name_lookup(sdg)

    execution_units = _flatten_plan(plan)
    total_calls = len(execution_units)

    metrics = MetricsCollector()
    task_records: list[dict[str, Any]] = []
    validation_records: list[dict[str, Any]] = []
    closed_obligations: list[dict[str, Any]] = []

    for call_index, (batch_index, function_node_id) in enumerate(
        execution_units, start=1
    ):
        function_name = name_by_id.get(function_node_id, function_node_id)
        task_id = f"batch:{batch_index}:{function_node_id}"
        calls_left = total_calls - call_index
        percent_complete = (
            (float(call_index - 1) / float(total_calls) * 100.0)
            if total_calls
            else 100.0
        )

        LOGGER.info(
            "call %s/%s | %.1f%% complete | %s left | fn=%s | provider=%s",
            call_index,
            total_calls,
            percent_complete,
            calls_left,
            function_name,
            getattr(runtime, "provider", "unknown"),
        )

        repaired = False
        completed = False

        for attempt in range(1, config.max_attempts_per_task + 1):
            context = build_function_context_package(
                sdg=sdg,
                function_node_id=function_node_id,
                repo_root=repo_root,
                depth_hint=attempt,
            )
            request = RuntimeTaskRequest(
                task_id=task_id,
                function_node_id=function_node_id,
                function_name=function_name,
                batch_index=batch_index,
                attempt=attempt,
                reason="topological_batch",
                context=context,
                mode="translate" if attempt == 1 else "repair",
            )

            runtime_result = runtime.run(request)
            guardrail_dir = output_dir / "validation" / task_id / f"attempt_{attempt}"
            validation = run_guardrails(
                config=config.guardrails,
                cwd=repo_root,
                task_label=task_id,
                result_dir=guardrail_dir,
            )

            task_record = {
                "task_id": task_id,
                "batch_index": batch_index,
                "task_order": call_index,
                "attempt": attempt,
                "reason": "topological_batch",
                "function_node_id": function_node_id,
                "function_name": function_name,
                "runtime_success": runtime_result.success,
                "validation_success": validation.success,
                "provider": getattr(runtime, "provider", "unknown"),
                "metrics": {
                    "latency_ms": runtime_result.metrics.latency_ms,
                    "token_usage": runtime_result.metrics.token_usage,
                    "subcall_count": runtime_result.metrics.subcall_count,
                    "recursion_depth": runtime_result.metrics.recursion_depth,
                },
                "interface_changes": list(runtime_result.interface_changes),
                "diagnostics": list(runtime_result.diagnostics),
                "translated_artifact": runtime_result.translated_artifact,
            }
            task_records.append(task_record)

            validation_records.append(
                {
                    "task_id": task_id,
                    "attempt": attempt,
                    "checks": list(validation.checks),
                    "stdout": validation.stdout,
                    "stderr": validation.stderr,
                }
            )

            attempt_success = runtime_result.success and validation.success
            repaired = repaired or (attempt > 1 and attempt_success)
            metrics.record_task(
                success=attempt_success,
                latency_ms=runtime_result.metrics.latency_ms,
                token_usage=runtime_result.metrics.token_usage,
                recursion_depth=runtime_result.metrics.recursion_depth,
                subcall_count=runtime_result.metrics.subcall_count,
                repaired=repaired,
            )

            if attempt_success:
                completed = True
                break

            LOGGER.warning(
                "call %s/%s failed attempt %s/%s | fn=%s",
                call_index,
                total_calls,
                attempt,
                config.max_attempts_per_task,
                function_name,
            )

        final_pct = (
            (float(call_index) / float(total_calls) * 100.0) if total_calls else 100.0
        )
        LOGGER.info(
            "call %s/%s done | %.1f%% complete | %s left | fn=%s | success=%s",
            call_index,
            total_calls,
            final_pct,
            calls_left,
            function_name,
            completed,
        )

    orchestration_report = {
        "plan": serialize_migration_plan(plan),
        "metrics": metrics.as_dict(),
        "obligations": {
            "closed": closed_obligations,
            "open_count": 0,
        },
        "tasks": task_records,
        "validations": validation_records,
    }

    _write_json(output_dir / "migration_plan.json", serialize_migration_plan(plan))
    _write_json(output_dir / "tasks.json", task_records)
    _write_json(output_dir / "validations.json", validation_records)
    _write_json(output_dir / "obligations.json", orchestration_report["obligations"])
    _write_json(output_dir / "report.json", orchestration_report)

    return orchestration_report


def planned_batches_from_sdg(sdg: nx.MultiDiGraph) -> MigrationPlan:
    return plan_migration_batches(sdg)
