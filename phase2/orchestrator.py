from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from phase1.pipeline import ImpactAnalyzer

from .context import build_function_context_package
from .metrics import MetricsCollector, baseline_comparison
from .planner import MigrationPlan, plan_migration_batches, serialize_migration_plan
from .runtime import Runtime, RuntimeTaskRequest
from .validation import GuardrailConfig, run_guardrails


@dataclass(frozen=True)
class OrchestratorConfig:
    max_attempts_per_task: int = 2
    guardrails: GuardrailConfig = field(default_factory=GuardrailConfig)


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


def _function_id_by_name(sdg: nx.MultiDiGraph) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for node_id, attrs in sdg.nodes(data=True):
        if attrs.get("node_type") != "Function":
            continue
        if attrs.get("external"):
            continue
        name = attrs.get("name")
        if isinstance(name, str) and name and name not in lookup:
            lookup[name] = node_id
    return lookup


def _obligation_task_id(function_name: str, index: int) -> str:
    return f"obligation:{function_name}:{index}"


def run_phase2_orchestration(
    *,
    sdg: nx.MultiDiGraph,
    repo_root: Path,
    output_dir: Path,
    runtime: Runtime,
    config: OrchestratorConfig,
    baseline_direct: dict[str, Any] | None = None,
    baseline_rag: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    plan = plan_migration_batches(sdg)
    analyzer = ImpactAnalyzer(sdg)
    name_by_id = _function_name_lookup(sdg)
    id_by_name = _function_id_by_name(sdg)

    metrics = MetricsCollector()
    closed_obligations: list[dict[str, Any]] = []
    open_obligations: deque[dict[str, Any]] = deque()
    seen_obligation_keys: set[tuple[str, str, str]] = set()
    task_records: list[dict[str, Any]] = []
    validation_records: list[dict[str, Any]] = []

    task_counter = 0

    def _run_single_task(
        *,
        function_node_id: str,
        batch_index: int,
        reason: str,
        task_id: str,
    ) -> tuple[bool, tuple[dict[str, Any], ...]]:
        nonlocal task_counter
        function_name = name_by_id.get(function_node_id, function_node_id)
        task_counter += 1

        interface_changes: tuple[dict[str, Any], ...] = ()
        repaired = False
        success = False

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
                reason=reason,
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
                "task_order": task_counter,
                "reason": reason,
                "attempt": attempt,
                "function_node_id": function_node_id,
                "function_name": function_name,
                "runtime_success": runtime_result.success,
                "validation_success": validation.success,
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
                success = True
                interface_changes = runtime_result.interface_changes
                break

        return success, interface_changes

    for batch in plan.batches:
        for function_node_id in batch.function_node_ids:
            task_id = f"batch:{batch.index}:{function_node_id}"
            success, interface_changes = _run_single_task(
                function_node_id=function_node_id,
                batch_index=batch.index,
                reason="topological_batch",
                task_id=task_id,
            )

            if not success:
                continue

            for change in interface_changes:
                impact = analyzer.analyze(change)
                for obligation_index, obligation in enumerate(
                    impact.get("obligations", []), start=1
                ):
                    target_name = str(obligation.get("target", "")).strip()
                    if not target_name:
                        continue
                    target_node_id = id_by_name.get(target_name)
                    if not target_node_id:
                        continue
                    action = str(obligation.get("action", "")).strip()
                    reason_text = str(obligation.get("reason", "")).strip()
                    key = (target_node_id, action, reason_text)
                    if key in seen_obligation_keys:
                        continue
                    seen_obligation_keys.add(key)
                    open_obligations.append(
                        {
                            "task_id": _obligation_task_id(
                                target_name, obligation_index
                            ),
                            "batch_index": batch.index,
                            "target_name": target_name,
                            "target_node_id": target_node_id,
                            "obligation": obligation,
                            "source_change": change,
                        }
                    )

    while open_obligations:
        obligation = open_obligations.popleft()
        success, interface_changes = _run_single_task(
            function_node_id=obligation["target_node_id"],
            batch_index=int(obligation["batch_index"]),
            reason=obligation["obligation"].get("action", "obligation"),
            task_id=obligation["task_id"],
        )

        if success:
            closed_obligations.append(
                {
                    "task_id": obligation["task_id"],
                    "target_name": obligation["target_name"],
                    "target_node_id": obligation["target_node_id"],
                    "action": obligation["obligation"].get("action"),
                    "reason": obligation["obligation"].get("reason"),
                    "source_change": obligation["source_change"],
                }
            )
            for change in interface_changes:
                impact = analyzer.analyze(change)
                for obligation_index, derived in enumerate(
                    impact.get("obligations", []), start=1
                ):
                    target_name = str(derived.get("target", "")).strip()
                    if not target_name:
                        continue
                    target_node_id = id_by_name.get(target_name)
                    if not target_node_id:
                        continue

                    action = str(derived.get("action", "")).strip()
                    reason_text = str(derived.get("reason", "")).strip()
                    key = (target_node_id, action, reason_text)
                    if key in seen_obligation_keys:
                        continue
                    seen_obligation_keys.add(key)

                    open_obligations.append(
                        {
                            "task_id": _obligation_task_id(
                                target_name, obligation_index
                            ),
                            "batch_index": int(obligation["batch_index"]),
                            "target_name": target_name,
                            "target_node_id": target_node_id,
                            "obligation": derived,
                            "source_change": change,
                        }
                    )

    orchestration_report = {
        "plan": serialize_migration_plan(plan),
        "metrics": metrics.as_dict(),
        "obligations": {
            "closed": closed_obligations,
            "open_count": len(open_obligations),
        },
        "tasks": task_records,
        "validations": validation_records,
    }

    evaluation = baseline_comparison(
        observed=metrics.as_dict(),
        direct_long_context=baseline_direct,
        rag_prompt=baseline_rag,
    )

    _write_json(output_dir / "migration_plan.json", serialize_migration_plan(plan))
    _write_json(output_dir / "tasks.json", task_records)
    _write_json(output_dir / "validations.json", validation_records)
    _write_json(output_dir / "obligations.json", orchestration_report["obligations"])
    _write_json(output_dir / "evaluation.json", evaluation)
    _write_json(output_dir / "report.json", orchestration_report)

    return orchestration_report


def planned_batches_from_sdg(sdg: nx.MultiDiGraph) -> MigrationPlan:
    return plan_migration_batches(sdg)
