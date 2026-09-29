"""Echo agent loop — section 7.1/7.2/7.3.

Orchestrator: detect customer/issue -> get_context (personal + collective) ->
build prompt (system rules + recalled memories + recent turns + user message) ->
generate with citations -> extract structured facts -> record_interaction ->
record_outcome on outcome events.

Model routing (section 10): openai/gpt-oss-120b primary, qwen/qwen3-32b fallback.
Error handling (section 7.3): retry once on malformed tool calls, fall back to
plain generation on repeated failure, degrade gracefully on Hindsight timeout.
Guardrails (section 7.4): no fabricated memories, no cross-customer leakage.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings
from app.memory import MemoryCitation, MemoryService, RecallResult

logger = logging.getLogger("echo.agent")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """\
You are Echo, a memory-first AI customer support agent.

CORE RULES (follow these exactly):
1. NEVER ask for information already in your memory. If you know the customer's name, plan, integrations, or prior issues, acknowledge them naturally — do not re-ask.
2. Acknowledge history naturally, not robotically. Say "I see the webhook issue is back" rather than "According to memory record #123...".
3. Cite which memories informed your reply using the [memory:ID] tag inline. These IDs appear in the transparency panel, not necessarily in prose.
4. NEVER re-suggest a fix that already failed for this customer. If memory shows a fix was attempted and the issue recurred, try a different approach.
5. Prefer fixes with high collective-success rates. If the collective bank says a fix type worked for similar issues, lead with it.
6. On frustration or repeat issues: apologize sincerely and prioritize. Escalate with a handoff brief when fixes are exhausted.
7. If memory conflicts with what the customer says, ask ONE clarifying question. Do not argue.
8. If you have no relevant memories, do NOT fabricate any. Just ask normally and help as a fresh agent would.
9. Keep replies concise and human. No bullet-point dumps unless the customer asks for steps.
10. When a fix is resolved or an outcome is clear, end with a natural commitment summary if any follow-up is promised.

Your reply must be valid JSON with this shape:
{
  "reply": "<your message to the customer>",
  "sentiment": "<neutral|frustrated|satisfied|confused|anxious>",
  "commitments": [{"text": "...", "due_date": "YYYY-MM-DD"}],
  "issue_type": "<detected issue type or null>",
  "fix_applied": "<description of fix if one was given, or null>",
  "outcome": "<resolved|failed|in_progress|null>"
}
"""


@dataclass
class AgentEvent:
    type: str  # "token" | "citations" | "degraded" | "done" | "error"
    data: dict[str, Any] = field(default_factory=dict)


async def run(
    customer_id: str,
    message: str,
    *,
    memory_on: bool = True,
    now: str,
    memory_service: MemoryService | None = None,
) -> AsyncIterator[AgentEvent]:
    """Run the full agent loop, yielding SSE events."""
    mem = memory_service or MemoryService()

    # 1. Recall context (if memory enabled)
    recall: RecallResult | None = None
    if memory_on:
        recall = await _safe_get_context(mem, customer_id, message)
        if recall and recall.citations:
            yield AgentEvent(
                type="citations",
                data={
                    "memories": [
                        {
                            "memory_id": c.memory_id,
                            "text": c.text,
                            "score": c.score,
                            "source": c.source,
                        }
                        for c in recall.citations
                    ]
                },
            )
        if recall and recall.degraded:
            yield AgentEvent(type="degraded", data={"error": recall.error})

    # 2. Build prompt
    messages = _build_prompt_messages(message, recall, memory_on)

    # 3. Generate with Groq (primary + fallback)
    raw_response, model_used = await _groq_generate(messages)

    if raw_response is None:
        yield AgentEvent(
            type="error",
            data={"error": "All Groq models failed to respond."},
        )
        return

    # 4. Parse structured reply (retry once on malformed JSON, section 7.3)
    parsed = _parse_agent_reply(raw_response)
    if parsed is None:
        # retry once with a plain-generation fallback
        logger.warning("malformed agent JSON, retrying with plain generation")
        fallback_messages = _build_fallback_messages(message, recall, memory_on)
        raw_response, model_used = await _groq_generate(fallback_messages)
        if raw_response:
            parsed = _parse_agent_reply(raw_response, lax=True)
        if parsed is None:
            parsed = {
                "reply": raw_response or "I'm sorry, I'm having trouble right now.",
                "sentiment": "neutral",
                "commitments": [],
                "issue_type": None,
                "fix_applied": None,
                "outcome": None,
            }

    reply_text = parsed.get("reply", "")
    sentiment = parsed.get("sentiment", "neutral")
    commitments = parsed.get("commitments", [])
    issue_type = parsed.get("issue_type")
    fix_applied = parsed.get("fix_applied")
    outcome = parsed.get("outcome")

    # 5. Stream tokens (simulate streaming from the complete reply)
    words = reply_text.split()
    for i in range(0, len(words), 3):
        chunk = " ".join(words[i : i + 3])
        yield AgentEvent(type="token", data={"text": chunk + (" " if i + 3 < len(words) else "")})

    # 6. Record interaction to Hindsight (distilled case note)
    if memory_on:
        case_note = _build_case_note_from_reply(
            customer_id=customer_id,
            message=message,
            reply=reply_text,
            sentiment=sentiment,
            commitments=commitments,
            issue_type=issue_type,
            fix_applied=fix_applied,
            outcome=outcome,
            now=now,
        )
        await mem.arecord_interaction(customer_id, case_note)

        # 7. Record outcome to collective bank if resolved/failed
        if outcome in ("resolved", "failed") and fix_applied:
            await mem.arecord_outcome(
                customer_id, issue_type or "unknown", fix_applied, outcome == "resolved"
            )

    # 8. Final event
    yield AgentEvent(
        type="done",
        data={
            "reply": reply_text,
            "sentiment": sentiment,
            "commitments": commitments,
            "issue_type": issue_type,
            "fix_applied": fix_applied,
            "outcome": outcome,
            "model": model_used,
            "recalled_memories": [
                {
                    "memory_id": c.memory_id,
                    "text": c.text,
                    "score": c.score,
                    "source": c.source,
                }
                for c in (recall.citations if recall else [])
            ],
            "degraded": recall.degraded if recall else False,
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _safe_get_context(
    mem: MemoryService, customer_id: str, message: str
) -> RecallResult:
    """Get context with full error protection — never raises."""
    try:
        return await mem.aget_context(customer_id, message)
    except Exception as e:
        logger.warning("get_context failed: %s", e)
        return RecallResult(degraded=True, error=str(e))


def _build_prompt_messages(
    message: str, recall: RecallResult | None, memory_on: bool
) -> list[dict[str, str]]:
    """Build the Groq chat messages per section 7.1/7.2."""
    memory_block = ""
    if memory_on and recall and recall.context_block:
        memory_block = f"\n\nRECALLED MEMORIES (use these, cite with [memory:ID]):\n{recall.context_block}\n"
    elif memory_on and recall and recall.degraded:
        memory_block = "\n\n[MEMORY DEGRADED — Hindsight unavailable. Reply without memory context and be transparent about it if asked.]\n"
    elif memory_on:
        memory_block = "\n\n[No relevant memories found for this customer. Do NOT fabricate memories.]\n"

    user_content = f"{memory_block}\nCUSTOMER MESSAGE:\n{message}\n\nRespond as Echo with valid JSON per the system prompt."

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _build_fallback_messages(
    message: str, recall: RecallResult | None, memory_on: bool
) -> list[dict[str, str]]:
    """Simplified prompt for retry after malformed JSON (section 7.3)."""
    memory_block = ""
    if memory_on and recall and recall.context_block:
        memory_block = f"\nContext from memory:\n{recall.context_block}\n"

    return [
        {
            "role": "system",
            "content": (
                "You are Echo, a customer support agent. Reply helpfully and concisely. "
                "You MUST respond as valid JSON: "
                '{"reply": "your message", "sentiment": "neutral", "commitments": [], "issue_type": null, "fix_applied": null, "outcome": null}'
            ),
        },
        {"role": "user", "content": f"{memory_block}\nCustomer message:\n{message}"},
    ]


async def _groq_generate(
    messages: list[dict[str, str]],
) -> tuple[str | None, str | None]:
    """Call Groq with primary model, fall back to secondary on failure."""
    for model in [settings.groq_primary_model, settings.groq_fallback_model]:
        try:
            result = await _call_groq(model, messages)
            if result:
                return result, model
        except Exception as e:
            logger.warning("Groq model %s failed: %s", model, e)
            continue
    return None, None


async def _call_groq(
    model: str, messages: list[dict[str, str]]
) -> str | None:
    """Single Groq chat completion call."""
    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 1024,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(GROQ_URL, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _parse_agent_reply(
    raw: str, *, lax: bool = False
) -> dict[str, Any] | None:
    """Parse the agent's JSON reply. Returns None on failure."""
    text = raw.strip()
    # strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        parsed = json.loads(text)
        if lax and "reply" not in parsed:
            parsed["reply"] = raw
        if "reply" in parsed:
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    if lax:
        return {
            "reply": raw,
            "sentiment": "neutral",
            "commitments": [],
            "issue_type": None,
            "fix_applied": None,
            "outcome": None,
        }
    return None


def _build_case_note_from_reply(
    *,
    customer_id: str,
    message: str,
    reply: str,
    sentiment: str,
    commitments: list[dict[str, Any]],
    issue_type: str | None,
    fix_applied: str | None,
    outcome: str | None,
    now: str,
) -> str:
    """Build a distilled case note from the current turn (section 6.2)."""
    return json.dumps(
        {
            "issue": issue_type or message[:100],
            "environment": "chat",
            "status": outcome or "in_progress",
            "opened_at": now,
            "closed_at": now if outcome == "resolved" else None,
            "attempted_fixes": fix_applied or reply[:200],
            "sentiment": sentiment,
            "commitments": commitments,
        },
        ensure_ascii=False,
    )
