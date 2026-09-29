"""Echo evaluation harness — eight workflow scenarios.

Each scenario simulates a realistic customer interaction and checks whether the
agent (with or without memory) produces a correct, context-aware response.

Scenarios
---------
1. repeat_issue        – Customer raises the same issue twice; agent should not
                         ask for information it already knows.
2. return_after_gap    – Customer returns after a long gap; agent should recall
                         prior context.
3. failed_fix_avoid    – A previous fix failed; agent should try a different
                         approach, not repeat the same fix.
4. overdue_commitment  – A commitment is past due; agent should acknowledge it.
5. frustrated_customer – Customer is clearly frustrated; agent should apologize
                         and prioritise.
6. new_customer        – No history at all; agent should ask normally.
7. memory_off_vs_on    – Run the *same* message with memory OFF then ON; compare.
8. forget              – After wiping memory, agent should behave like new.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agent import run as agent_run
from app.config import settings, virtual_clock
from app.memory import MemoryService

logger = logging.getLogger("echo.eval")

EVAL_OUTPUT_DIR = Path("eval_results")

PRIYA_ID = "00000000-0000-4000-8000-000000000001"
MARCUS_ID = "00000000-0000-4000-8000-000000000002"
ELENA_ID = "00000000-0000-4000-8000-000000000003"

# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

SCENARIO_REGISTRY: dict[str, dict[str, Any]] = {
    "repeat_issue": {
        "customer_id": PRIYA_ID,
        "message": "The webhook issue is back again. We're seeing the same delivery failures as last time.",
        "check": "Agent should acknowledge the prior webhook case without re-asking for details.",
    },
    "return_after_gap": {
        "customer_id": PRIYA_ID,
        "message": "Hi, I haven't been in touch for a while. Just wanted to check if the webhook stability has improved.",
        "check": "Agent should recall the customer's history and reference the prior webhook issues.",
    },
    "failed_fix_avoidance": {
        "customer_id": PRIYA_ID,
        "message": "Webhooks are failing again. Last time you regenerated the signing token but it didn't last.",
        "check": "Agent should NOT suggest regenerating the signing token again since it already failed.",
    },
    "overdue_commitment": {
        "customer_id": PRIYA_ID,
        "message": "I was promised a follow-up after the Friday release. It's been over a week now.",
        "check": "Agent should acknowledge the missed commitment and apologise.",
    },
    "frustrated_customer": {
        "customer_id": PRIYA_ID,
        "message": "I'm really frustrated — this is the THIRD time this has happened and nobody seems to care!",
        "check": "Agent should apologise sincerely, detect frustrated sentiment, and prioritise.",
    },
    "new_customer": {
        "customer_id": "eval_new_" + str(int(time.time())),
        "message": "Hi, I just signed up and I'm having trouble setting up my first integration.",
        "check": "Agent should help without any assumed context; no fabricated memories.",
    },
    "memory_off_vs_on": {
        "customer_id": PRIYA_ID,
        "message": "The webhook issue is back again. We're seeing the same delivery failures as last time.",
        "check": "Memory ON reply should reference prior history; Memory OFF should not.",
    },
    "forget": {
        "customer_id": PRIYA_ID,
        "message": "The webhook issue is back again. We're seeing the same delivery failures as last time.",
        "check": "After forget, agent should treat customer as new — no recalled context.",
    },
}


@dataclass
class ScenarioResult:
    scenario: str
    memory_on: bool
    reply: str = ""
    sentiment: str = ""
    commitments: list[dict] = field(default_factory=list)
    issue_type: str | None = None
    fix_applied: str | None = None
    outcome: str | None = None
    memories_recalled: int = 0
    degraded: bool = False
    model: str | None = None
    check_description: str = ""
    elapsed_seconds: float = 0.0
    error: str | None = None


@dataclass
class EvalReport:
    ran_at: str = ""
    total_scenarios: int = 0
    results: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def _run_single_scenario(
    scenario_name: str,
    customer_id: str,
    message: str,
    check: str,
    memory_on: bool,
    memory_service: MemoryService,
) -> ScenarioResult:
    """Run one scenario through the agent loop and collect the result."""
    result = ScenarioResult(
        scenario=scenario_name,
        memory_on=memory_on,
        check_description=check,
    )
    start = time.monotonic()
    try:
        final_data: dict[str, Any] = {}
        async for event in agent_run(
            customer_id=customer_id,
            message=message,
            memory_on=memory_on,
            now=virtual_clock.now_iso,
            memory_service=memory_service,
        ):
            if event.type == "done":
                final_data = event.data
            elif event.type == "error":
                result.error = event.data.get("error", "unknown error")

        if final_data:
            result.reply = final_data.get("reply", "")
            result.sentiment = final_data.get("sentiment", "")
            result.commitments = final_data.get("commitments", [])
            result.issue_type = final_data.get("issue_type")
            result.fix_applied = final_data.get("fix_applied")
            result.outcome = final_data.get("outcome")
            result.memories_recalled = len(final_data.get("recalled_memories", []))
            result.degraded = final_data.get("degraded", False)
            result.model = final_data.get("model")
    except Exception as e:
        result.error = str(e)
    result.elapsed_seconds = round(time.monotonic() - start, 2)
    return result


async def run_evaluation(
    scenarios: list[str] | None = None,
    memory_on: bool = True,
) -> EvalReport:
    """Run selected (or all) evaluation scenarios and return a report.

    The report is also saved to ``eval_results/eval_<timestamp>.json``.
    """
    mem = MemoryService()
    to_run = scenarios or list(SCENARIO_REGISTRY.keys())
    report = EvalReport(
        ran_at=datetime.now(timezone.utc).isoformat(),
        total_scenarios=len(to_run),
    )

    for name in to_run:
        spec = SCENARIO_REGISTRY.get(name)
        if spec is None:
            report.results.append({"scenario": name, "error": "unknown scenario"})
            continue

        if name == "memory_off_vs_on":
            # Run twice: OFF then ON
            off_result = await _run_single_scenario(
                f"{name}_OFF", spec["customer_id"], spec["message"],
                spec["check"], memory_on=False, memory_service=mem,
            )
            on_result = await _run_single_scenario(
                f"{name}_ON", spec["customer_id"], spec["message"],
                spec["check"], memory_on=True, memory_service=mem,
            )
            report.results.append(asdict(off_result))
            report.results.append(asdict(on_result))
            continue

        if name == "forget":
            # Wipe memory first, then run
            await mem.aforget(spec["customer_id"])
            result = await _run_single_scenario(
                name, spec["customer_id"], spec["message"],
                spec["check"], memory_on=True, memory_service=mem,
            )
            report.results.append(asdict(result))
            continue

        result = await _run_single_scenario(
            name, spec["customer_id"], spec["message"],
            spec["check"], memory_on=memory_on, memory_service=mem,
        )
        report.results.append(asdict(result))

    # Summary metrics
    on_results = [r for r in report.results if r.get("memory_on") is True and not r.get("error")]
    off_results = [r for r in report.results if r.get("memory_on") is False and not r.get("error")]

    report.summary = {
        "memory_on_avg_memories_recalled": (
            round(sum(r["memories_recalled"] for r in on_results) / len(on_results), 2)
            if on_results else 0
        ),
        "memory_off_avg_memories_recalled": (
            round(sum(r["memories_recalled"] for r in off_results) / len(off_results), 2)
            if off_results else 0
        ),
        "scenarios_with_errors": sum(1 for r in report.results if r.get("error")),
        "total_elapsed_seconds": round(sum(r.get("elapsed_seconds", 0) for r in report.results), 2),
    }

    # Persist
    EVAL_OUTPUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = EVAL_OUTPUT_DIR / f"eval_{ts}.json"
    out_file.write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False))
    logger.info("Eval results saved to %s", out_file)

    return report
