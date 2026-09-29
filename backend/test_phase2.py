#!/usr/bin/env python3
"""End-to-end Phase 2 test — runs one real conversation turn against Priya
through Hindsight + Groq, then prints the raw final SSE event JSON and one
retained case note as written to Hindsight.

Usage:
  cd backend && python3 test_phase2.py

Requires GROQ_API_KEY and HINDSIGHT_API_KEY in environment.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.agent import run as agent_run
from app.memory import MemoryService

CUSTOMER = "c_priya"
DB_ID = "00000000-0000-4000-8000-000000000001"

SEED_NOTES = [
    json.dumps({
        "issue": "Webhook deliveries stopped after Business plan upgrade",
        "environment": "slack",
        "status": "closed",
        "opened_at": "2025-12-09T10:00:00+00:00",
        "closed_at": "2025-12-09T13:30:00+00:00",
        "attempted_fixes": "Customer reported webhook deliveries stopped after Business plan upgrade. Agent regenerated signing token and replayed failed deliveries successfully.",
        "sentiment": "frustrated",
        "commitments": "Follow up with Priya after the Friday release to confirm webhook stability. (due 2025-12-20)",
    }, ensure_ascii=False),
    json.dumps({
        "issue": "Webhook deliveries failing again",
        "environment": "chat",
        "status": "open",
        "opened_at": "2025-12-19T09:00:00+00:00",
        "closed_at": None,
        "attempted_fixes": "Customer reports webhook issue returned after another release.",
        "sentiment": "frustrated",
        "commitments": "Follow up with Priya after the Friday release to confirm webhook stability. (due 2025-12-20)",
    }, ensure_ascii=False),
]

TEST_MESSAGE = "The webhook issue is back again. We're seeing the same delivery failures as last time."


async def main():
    groq_key = os.environ.get("GROQ_API_KEY", "")
    hindsight_key = os.environ.get("HINDSIGHT_API_KEY", "")

    if not groq_key:
        print("ERROR: GROQ_API_KEY not set in environment.")
        return
    if not hindsight_key:
        print("ERROR: HINDSIGHT_API_KEY not set in environment.")
        return

    mem = MemoryService()

    # Step 1: Seed Hindsight with Priya's existing case notes
    print("=" * 70)
    print("STEP 1: Seeding Hindsight with Priya's existing ticket history")
    print("=" * 70)
    for note in SEED_NOTES:
        result = await mem.arecord_interaction(DB_ID, note)
        print(f"  Retained: {result}")
    print()

    # Step 2: Recall context
    print("=" * 70)
    print("STEP 2: Recalling context for test message")
    print(f"  Query: {TEST_MESSAGE}")
    print("=" * 70)
    recall = await mem.aget_context(DB_ID, TEST_MESSAGE)
    print(f"  Degraded: {recall.degraded}")
    print(f"  Citations: {len(recall.citations)}")
    for c in recall.citations:
        print(f"    [{c.source}] {c.memory_id} (score={c.score:.3f})")
        print(f"      {c.text[:120]}")
    print()

    # Step 3: Run the full agent loop
    print("=" * 70)
    print("STEP 3: Running agent loop (Groq + Hindsight)")
    print("=" * 70)

    final_event = None
    token_text = ""
    async for event in agent_run(
        customer_id=DB_ID,
        message=TEST_MESSAGE,
        memory_on=True,
        now="2026-01-01T09:00:00+00:00",
        memory_service=mem,
    ):
        if event.type == "token":
            token_text += event.data["text"]
        elif event.type == "citations":
            print(f"  [citations] {len(event.data['memories'])} memories recalled")
        elif event.type == "degraded":
            print(f"  [degraded] {event.data['error']}")
        elif event.type == "done":
            final_event = event.data
        elif event.type == "error":
            print(f"  [error] {event.data['error']}")

    print(f"\n  Agent reply: {final_event.get('reply', '')[:300] if final_event else 'N/A'}")
    print()

    print("=" * 70)
    print("FINAL SSE EVENT (raw JSON):")
    print("=" * 70)
    print(json.dumps(final_event, indent=2, ensure_ascii=False))

    # Step 4: Show what was retained to Hindsight from this turn
    print()
    print("=" * 70)
    print("RETAINED CASE NOTES (recent, from Hindsight):")
    print("=" * 70)
    try:
        memories = await mem.alist_memories(DB_ID, limit=5)
        for item in memories[-3:]:
            mid = getattr(item, "id", "N/A")
            mtext = getattr(item, "text", getattr(item, "content", "N/A"))
            print(f"  ID: {mid}")
            print(f"  Text: {str(mtext)[:200]}")
            print()
        if not memories:
            print("  (no memories returned — list_memories may use a different response shape)")
    except Exception as e:
        print(f"  Could not list memories: {e}")

    # Step 5: Degraded mode test
    print("=" * 70)
    print("STEP 5: Degraded mode simulation (Hindsight unreachable)")
    print("=" * 70)
    import app.config as cfg
    original_url = cfg.settings.hindsight_base_url
    cfg.settings.hindsight_base_url = "https://10.255.255.1"
    bad_mem = MemoryService()
    bad_recall = await bad_mem.aget_context(DB_ID, TEST_MESSAGE)
    print(f"  Degraded: {bad_recall.degraded}")
    print(f"  Error: {bad_recall.error}")
    print(f"  Citations: {len(bad_recall.citations)}")
    print(f"  (Should be degraded=True, 0 citations, no crash)")
    cfg.settings.hindsight_base_url = original_url

    print()
    print("=" * 70)
    print("ALL TESTS COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
