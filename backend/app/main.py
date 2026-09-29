"""Echo FastAPI app — API contract per section 9.

Phase 2+: chat SSE is wired to the real agent loop (Groq + Hindsight).
Customers, outcome, and forget are DB-backed. Virtual clock is persisted and
calculates overdue commitments. Evaluation harness covers 8 scenarios.
Demo reset returns the system to a known state.
"""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent import run as agent_run
from app.config import settings, virtual_clock
from app.eval import run_evaluation
from app.memory import MemoryService

app = FastAPI(title="Echo", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

memory = MemoryService()

DEMO_CUSTOMERS = [
    {
        "id": "00000000-0000-4000-8000-000000000001",
        "name": "Priya Nair",
        "email": "priya.nair@example.com",
        "company": "Acme Cloud",
        "plan": "Business",
        "integrations": ["Slack", "Stripe"],
        "created_at": "2024-03-15T00:00:00+00:00",
    },
    {
        "id": "00000000-0000-4000-8000-000000000002",
        "name": "Marcus Lee",
        "email": "marcus.lee@example.com",
        "company": "Northstar Labs",
        "plan": "Pro",
        "integrations": ["GitHub", "Linear"],
        "created_at": "2024-07-01T00:00:00+00:00",
    },
    {
        "id": "00000000-0000-4000-8000-000000000003",
        "name": "Elena Torres",
        "email": "elena.torres@example.com",
        "company": "Orbit Works",
        "plan": "Business",
        "integrations": ["HubSpot", "Slack"],
        "created_at": "2023-11-20T00:00:00+00:00",
    },
]

DEMO_CASE_NOTES = {
    DEMO_CUSTOMERS[0]["id"]: [
        {
            "issue": "Webhook deliveries stopped after Business plan upgrade",
            "environment": "Slack",
            "status": "closed",
            "opened_at": "2025-12-09T10:00:00+00:00",
            "attempted_fixes": "Regenerated the signing token and replayed failed deliveries successfully.",
            "sentiment": "frustrated",
            "commitments": [{"text": "Follow up after the Friday release to confirm webhook stability.", "due_date": "2025-12-20"}],
        },
        {
            "issue": "Webhook deliveries failing again",
            "environment": "chat",
            "status": "open",
            "opened_at": "2025-12-19T09:00:00+00:00",
            "attempted_fixes": "Customer reports the issue returned after another release.",
            "sentiment": "frustrated",
            "commitments": [],
        },
    ],
    DEMO_CUSTOMERS[1]["id"]: [
        {
            "issue": "Duplicate charge for the current billing period",
            "environment": "billing",
            "status": "open",
            "opened_at": "2025-12-18T11:00:00+00:00",
            "attempted_fixes": "A duplicate charge was reported previously; verify the latest invoice before retrying payment.",
            "sentiment": "concerned",
            "commitments": [{"text": "Send the corrected invoice PDF.", "due_date": "2025-12-20"}],
        },
    ],
    DEMO_CUSTOMERS[2]["id"]: [
        {
            "issue": "SSO redirects the team back to the login screen",
            "environment": "SAML SSO",
            "status": "open",
            "opened_at": "2025-12-17T14:00:00+00:00",
            "attempted_fixes": "The issue followed an identity provider certificate rotation; check certificate validity and ACS URL before changing the configuration.",
            "sentiment": "anxious",
            "commitments": [{"text": "Check SSO login after the next certificate rotation.", "due_date": "2026-01-15"}],
        },
    ],
}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    customer_id: str
    message: str
    memory_enabled: bool = True
    now: str | None = None


class CustomerCreate(BaseModel):
    name: str
    company: str
    plan: str
    email: str
    integrations: list[str] = Field(default_factory=list)


class OutcomeRequest(BaseModel):
    fix_id: str
    worked: bool


class TimeJumpRequest(BaseModel):
    days: int


class EvalRequest(BaseModel):
    scenarios: list[str] | None = None
    memory_on: bool = True


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "virtual_now": virtual_clock.now_iso,
        "groq_configured": bool(settings.groq_api_key),
        "hindsight_configured": bool(settings.hindsight_api_key),
    }


# ---------------------------------------------------------------------------
# Customers (demo fixtures + Hindsight registry)
# ---------------------------------------------------------------------------


@app.get("/api/customers")
async def list_customers() -> list[dict[str, Any]]:
    customers = {customer["id"]: customer for customer in DEMO_CUSTOMERS}
    if settings.hindsight_api_key:
        for customer in await memory.alist_customer_profiles():
            customers[customer["id"]] = customer
    return sorted(customers.values(), key=lambda customer: customer["name"].casefold())


@app.get("/api/customers/{customer_id}")
async def get_customer(customer_id: str) -> dict[str, Any]:
    for customer in await list_customers():
        if customer["id"] == customer_id:
            return customer
    raise HTTPException(404, "customer not found")


@app.post("/api/customers")
async def add_customer(customer: CustomerCreate) -> dict[str, Any]:
    profile = customer.model_dump()
    profile.update(
        id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    if not await memory.arecord_customer_profile(profile):
        raise HTTPException(503, "Could not save the customer profile to Hindsight.")
    return profile


# ---------------------------------------------------------------------------
# Chat (SSE — real agent loop)
# ---------------------------------------------------------------------------


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    now = req.now or virtual_clock.now_iso

    async def stream() -> AsyncIterator[bytes]:
        yield _sse("status", {"agent": "echo", "memory_enabled": req.memory_enabled})
        try:
            async for event in agent_run(
                customer_id=req.customer_id,
                message=req.message,
                memory_on=req.memory_enabled,
                now=now,
                memory_service=memory,
            ):
                yield _sse(event.type, event.data)
        except Exception as e:
            yield _sse("error", {"error": str(e)})

    return StreamingResponse(stream(), media_type="text/event-stream")


def _sse(event_type: str, data: dict[str, Any]) -> bytes:
    return f"event: {event_type}\n".encode() + (
        f"data: {json.dumps(data)}\n\n".encode()
    )


# ---------------------------------------------------------------------------
# Seed Hindsight with the built-in demo case notes
# ---------------------------------------------------------------------------


@app.post("/api/customers/{customer_id}/seed-memory")
async def seed_memory(customer_id: str) -> dict[str, Any]:
    await get_customer(customer_id)
    count = 0
    for note in DEMO_CASE_NOTES.get(customer_id, []):
        if await memory.arecord_interaction(customer_id, json.dumps(note)):
            count += 1
    return {"customer_id": customer_id, "notes_retained": count}


@app.get("/api/customers/{customer_id}/memories")
async def list_memories(customer_id: str) -> dict[str, Any]:
    await get_customer(customer_id)
    items = await memory.alist_memories(customer_id, limit=20)
    result = []
    for item in items:
        if isinstance(item, dict):
            memory_id = item.get("id", "")
            text = item.get("text") or item.get("content", "")
            scores = item.get("scores") or {}
            score = scores.get("final", 0) if isinstance(scores, dict) else 0
        else:
            memory_id = getattr(item, "id", "")
            text = getattr(item, "text", getattr(item, "content", ""))
            scores = getattr(item, "scores", None)
            score = getattr(scores, "final", 0) if scores else 0
        result.append({"id": str(memory_id), "text": str(text), "scores": {"final": score}})
    return {"memories": result}


# ---------------------------------------------------------------------------
# Handoff brief
# ---------------------------------------------------------------------------


@app.get("/api/customers/{customer_id}/brief")
async def handoff_brief(customer_id: str) -> dict[str, Any]:
    await get_customer(customer_id)
    tickets = []
    commitments = []
    for item in await memory.alist_memories(customer_id, limit=20):
        text = item.get("text", "") if isinstance(item, dict) else getattr(item, "text", "")
        try:
            note = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(note, dict):
            continue
        tickets.append({
            "id": str(note.get("id") or len(tickets)),
            "subject": note.get("issue", "Support case"),
            "status": note.get("status", "open"),
            "opened_at": note.get("opened_at") or virtual_clock.now_iso,
        })
        note_commitments = note.get("commitments", [])
        if isinstance(note_commitments, str) and note_commitments:
            note_commitments = [{"text": note_commitments, "due_date": ""}]
        if isinstance(note_commitments, list) and note.get("status") not in ("closed", "resolved"):
            commitments.extend(
                commitment for commitment in note_commitments if isinstance(commitment, dict)
            )
    tickets.sort(key=lambda ticket: ticket["opened_at"], reverse=True)

    # Calculate overdue status for commitments
    overdue = virtual_clock.overdue_commitments(commitments)
    overdue_texts = {c["text"] for c in overdue}
    for c in commitments:
        c["overdue"] = c["text"] in overdue_texts

    return {
        "customer_id": customer_id,
        "summary": f"{len(tickets)} recent cases, {len(commitments)} open commitments.",
        "tickets": tickets[:5],
        "open_commitments": commitments,
        "overdue_commitments": overdue,
    }


# ---------------------------------------------------------------------------
# Time-jump (virtual clock) — fully wired
# ---------------------------------------------------------------------------


@app.get("/api/virtual-clock")
def get_virtual_clock() -> dict[str, Any]:
    return {"virtual_now": virtual_clock.now_iso}


@app.post("/api/customers/{customer_id}/time-jump")
async def time_jump(customer_id: str, req: TimeJumpRequest) -> dict[str, Any]:
    new_now = virtual_clock.advance(req.days)

    # Collect all open commitments for this customer and flag overdue ones
    all_commitments: list[dict] = []
    for note in DEMO_CASE_NOTES.get(customer_id, []):
        note_commitments = note.get("commitments", [])
        if isinstance(note_commitments, list):
            all_commitments.extend(c for c in note_commitments if isinstance(c, dict))

    # Also check Hindsight-stored commitments
    try:
        items = await memory.alist_memories(customer_id, limit=20)
        for item in items:
            text = item.get("text", "") if isinstance(item, dict) else getattr(item, "text", "")
            try:
                note = json.loads(text)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(note, dict):
                nc = note.get("commitments", [])
                if isinstance(nc, list):
                    all_commitments.extend(c for c in nc if isinstance(c, dict))
    except Exception:
        pass

    overdue = virtual_clock.overdue_commitments(all_commitments)

    return {
        "customer_id": customer_id,
        "virtual_now": new_now,
        "days_advanced": req.days,
        "overdue_commitments": overdue,
        "total_commitments": len(all_commitments),
    }


# ---------------------------------------------------------------------------
# Outcome
# ---------------------------------------------------------------------------


@app.post("/api/customers/{customer_id}/outcome")
async def record_outcome(customer_id: str, req: OutcomeRequest) -> dict[str, Any]:
    await get_customer(customer_id)
    await memory.arecord_outcome(customer_id, "unknown", req.fix_id, req.worked)
    return {
        "recorded": True,
        "customer_id": customer_id,
        "fix_id": req.fix_id,
        "worked": req.worked,
    }


# ---------------------------------------------------------------------------
# Forget memory
# ---------------------------------------------------------------------------


@app.delete("/api/customers/{customer_id}/memory")
async def forget_memory(customer_id: str) -> dict[str, Any]:
    await get_customer(customer_id)
    await memory.aforget(customer_id)
    return {"forgotten": True, "customer_id": customer_id}


# ---------------------------------------------------------------------------
# Evaluation — real 8-scenario harness
# ---------------------------------------------------------------------------


@app.post("/api/eval/run")
async def eval_run(req: EvalRequest) -> dict[str, Any]:
    report = await run_evaluation(
        scenarios=req.scenarios,
        memory_on=req.memory_on,
    )
    return {
        "ran_at": report.ran_at,
        "total_scenarios": report.total_scenarios,
        "results": report.results,
        "summary": report.summary,
    }


# ---------------------------------------------------------------------------
# Demo reset — return the system to a known starting state
# ---------------------------------------------------------------------------


@app.post("/api/demo/reset")
async def demo_reset() -> dict[str, Any]:
    """Reset virtual clock, wipe all demo customer memories, remove eval output."""
    # Reset virtual clock
    new_time = virtual_clock.reset()

    # Wipe memory for all demo customers
    forgotten = []
    for customer in DEMO_CUSTOMERS:
        try:
            await memory.aforget(customer["id"])
            forgotten.append(customer["id"])
        except Exception:
            pass

    # Remove eval results
    eval_dir = __import__("pathlib").Path("eval_results")
    eval_cleaned = 0
    if eval_dir.exists():
        for f in eval_dir.glob("*.json"):
            f.unlink()
            eval_cleaned += 1

    return {
        "reset": True,
        "virtual_now": new_time,
        "memories_forgotten": forgotten,
        "eval_files_removed": eval_cleaned,
    }
