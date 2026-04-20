from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ValidationResult:
    success: bool
    checks: tuple[dict[str, Any], ...]
    stdout: str
    stderr: str


@dataclass(frozen=True)
class GuardrailConfig:
    enabled: bool = False
    compile_cmd: tuple[str, ...] = ("cargo", "check")
    test_cmd: tuple[str, ...] = ()
    timeout_sec: int = 90


def _run_command(
    command: tuple[str, ...], cwd: Path, timeout_sec: int
) -> tuple[bool, str, str]:
    if not command:
        return True, "", ""

    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        return result.returncode == 0, result.stdout, result.stderr
    except FileNotFoundError as exc:
        return False, "", str(exc)
    except subprocess.TimeoutExpired as exc:
        return False, exc.stdout or "", f"Command timed out after {timeout_sec}s"


def run_guardrails(
    *,
    config: GuardrailConfig,
    cwd: Path,
    task_label: str,
    result_dir: Path,
) -> ValidationResult:
    if not config.enabled:
        checks = (
            {
                "name": "guardrails",
                "status": "skipped",
                "reason": "disabled",
                "task": task_label,
            },
        )
        return ValidationResult(success=True, checks=checks, stdout="", stderr="")

    checks: list[dict[str, Any]] = []
    combined_stdout = []
    combined_stderr = []
    overall_success = True

    ok_compile, out_compile, err_compile = _run_command(
        config.compile_cmd, cwd=cwd, timeout_sec=config.timeout_sec
    )
    checks.append(
        {
            "name": "compile",
            "command": list(config.compile_cmd),
            "status": "passed" if ok_compile else "failed",
            "task": task_label,
        }
    )
    combined_stdout.append(out_compile)
    combined_stderr.append(err_compile)
    overall_success = overall_success and ok_compile

    if overall_success and config.test_cmd:
        ok_test, out_test, err_test = _run_command(
            config.test_cmd, cwd=cwd, timeout_sec=config.timeout_sec
        )
        checks.append(
            {
                "name": "tests",
                "command": list(config.test_cmd),
                "status": "passed" if ok_test else "failed",
                "task": task_label,
            }
        )
        combined_stdout.append(out_test)
        combined_stderr.append(err_test)
        overall_success = overall_success and ok_test
    elif config.test_cmd:
        checks.append(
            {
                "name": "tests",
                "command": list(config.test_cmd),
                "status": "skipped",
                "reason": "compile_failed",
                "task": task_label,
            }
        )

    result_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "task": task_label,
        "success": overall_success,
        "checks": checks,
    }
    (result_dir / "validation.json").write_text(json.dumps(payload, indent=2) + "\n")

    return ValidationResult(
        success=overall_success,
        checks=tuple(checks),
        stdout="\n".join(filter(None, combined_stdout)),
        stderr="\n".join(filter(None, combined_stderr)),
    )
