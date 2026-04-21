from __future__ import annotations

import json
import subprocess
from pathlib import Path

from phase1.pipeline import analyze_phase1
from phase2.context import build_function_context_package, function_dependencies
from phase2.orchestrator import OrchestratorConfig, run_phase2_orchestration
from phase2.planner import build_function_dependency_graph, plan_migration_batches
from phase2.runtime import LLMRuntime, MockRuntime, build_runtime
from phase2.validation import GuardrailConfig


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT / "repo"


def test_phase21_dependency_graph_and_batches():
    analysis = analyze_phase1(REPO_ROOT)

    dep_graph = build_function_dependency_graph(analysis.sdg)
    assert dep_graph.number_of_nodes() == 8

    assert dep_graph.has_edge("function:calculate_subtotal", "function:checkout_total")
    assert dep_graph.has_edge(
        "function:apply_global_discount", "function:checkout_total"
    )
    assert dep_graph.has_edge("function:checkout_total", "function:main")

    plan = plan_migration_batches(analysis.sdg)
    assert plan.internal_function_count == 8
    assert plan.scc_count == 8
    assert len(plan.batches) >= 3

    node_to_batch = plan.node_to_batch_index()
    for source, target in dep_graph.edges:
        assert node_to_batch[source] <= node_to_batch[target]


def test_phase22_context_package_and_dependencies():
    analysis = analyze_phase1(REPO_ROOT)
    deps = function_dependencies(analysis.sdg, "function:checkout_total")

    assert deps["callees"] == [
        "function:apply_global_discount",
        "function:calculate_subtotal",
        "function:set_last_total",
    ]
    assert deps["uses_types"] == ["type:Cart"]

    context = build_function_context_package(
        sdg=analysis.sdg,
        function_node_id="function:checkout_total",
        repo_root=REPO_ROOT,
        depth_hint=2,
    )
    assert context["target"]["name"] == "checkout_total"
    assert context["depth_hint"] == 2
    assert context["code_slice"]["exists"] is True
    assert "checkout_total" in context["code_slice"]["source"]


def test_phase23_orchestration_simple_loop_with_retry(tmp_path):
    analysis = analyze_phase1(REPO_ROOT)

    runtime = MockRuntime(fail_first_attempt_for={"main"})

    report = run_phase2_orchestration(
        sdg=analysis.sdg,
        repo_root=REPO_ROOT,
        output_dir=tmp_path / "phase2",
        runtime=runtime,
        config=OrchestratorConfig(
            max_attempts_per_task=2,
            guardrails=GuardrailConfig(enabled=False),
        ),
    )

    metrics = report["metrics"]
    assert metrics["total_tasks"] >= 9
    assert metrics["repair_loops"] >= 1

    assert report["obligations"]["closed"] == []
    assert report["obligations"]["open_count"] == 0

    assert (tmp_path / "phase2" / "migration_plan.json").exists()
    assert (tmp_path / "phase2" / "tasks.json").exists()
    assert (tmp_path / "phase2" / "report.json").exists()


def test_phase24_guardrail_failure_and_retry(tmp_path):
    analysis = analyze_phase1(REPO_ROOT)
    runtime = MockRuntime(fail_first_attempt_for={"calculate_subtotal"})

    report = run_phase2_orchestration(
        sdg=analysis.sdg,
        repo_root=REPO_ROOT,
        output_dir=tmp_path / "phase2_guard",
        runtime=runtime,
        config=OrchestratorConfig(
            max_attempts_per_task=2,
            guardrails=GuardrailConfig(
                enabled=True,
                compile_cmd=("python3", "-c", "import sys; sys.exit(0)"),
                test_cmd=("python3", "-c", "import sys; sys.exit(0)"),
                timeout_sec=10,
            ),
        ),
    )

    assert report["metrics"]["total_tasks"] >= 8
    assert report["metrics"]["successful_tasks"] >= 8

    validations_path = tmp_path / "phase2_guard" / "validations.json"
    payload = json.loads(validations_path.read_text())
    assert payload
    assert all("checks" in record for record in payload)


def test_phase25_runtime_builder_for_ollama_and_groq():
    runtime_ollama = build_runtime(
        "llm",
        llm_provider="ollama",
        llm_model="llama3.1",
        llm_base_url="http://localhost:11434/v1",
    )
    assert isinstance(runtime_ollama, LLMRuntime)
    assert runtime_ollama.provider == "ollama"

    runtime_mock = build_runtime("mock")
    assert isinstance(runtime_mock, MockRuntime)


def test_phase2_cli_entrypoint(tmp_path):
    phase1_out = tmp_path / "phase1_cli_out"
    phase1_command = [
        "python3",
        "-m",
        "phase1",
        "--repo",
        str(REPO_ROOT),
        "--out",
        str(phase1_out),
    ]
    subprocess.run(
        phase1_command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    output_dir = tmp_path / "phase2_cli_out"

    command = [
        "python3",
        "-m",
        "phase2",
        "--repo",
        str(REPO_ROOT),
        "--sdg",
        str(phase1_out / "sdg_v1.json"),
        "--out",
        str(output_dir),
        "--runtime",
        "mock",
        "--max-attempts",
        "2",
    ]

    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    summary = json.loads(result.stdout)
    assert summary["runtime"] == "mock"
    assert summary["provider"] == "mock"
    assert summary["tasks"] >= 8
    assert summary["failed_tasks"] == 0
    assert (output_dir / "report.json").exists()
