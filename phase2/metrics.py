from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MetricsCollector:
    total_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    repair_loops: int = 0
    total_latency_ms: int = 0
    total_token_usage: int = 0
    max_recursion_depth: int = 0
    total_subcalls: int = 0

    def record_task(
        self,
        *,
        success: bool,
        latency_ms: int,
        token_usage: int,
        recursion_depth: int,
        subcall_count: int,
        repaired: bool,
    ) -> None:
        self.total_tasks += 1
        if success:
            self.successful_tasks += 1
        else:
            self.failed_tasks += 1
        if repaired:
            self.repair_loops += 1

        self.total_latency_ms += max(0, latency_ms)
        self.total_token_usage += max(0, token_usage)
        self.max_recursion_depth = max(
            self.max_recursion_depth, max(1, recursion_depth)
        )
        self.total_subcalls += max(0, subcall_count)

    def as_dict(self) -> dict[str, Any]:
        avg_latency = (
            float(self.total_latency_ms) / float(self.total_tasks)
            if self.total_tasks
            else 0.0
        )
        avg_tokens = (
            float(self.total_token_usage) / float(self.total_tasks)
            if self.total_tasks
            else 0.0
        )

        return {
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "failed_tasks": self.failed_tasks,
            "repair_loops": self.repair_loops,
            "total_latency_ms": self.total_latency_ms,
            "avg_latency_ms": avg_latency,
            "total_token_usage": self.total_token_usage,
            "avg_token_usage": avg_tokens,
            "max_recursion_depth": self.max_recursion_depth,
            "total_subcalls": self.total_subcalls,
        }
