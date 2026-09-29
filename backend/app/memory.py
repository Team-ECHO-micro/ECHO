"""MemoryService — real Hindsight Cloud wrapper (section 6).

Two-tier bank design (section 6.1):
  - Personal bank per customer:  bank ID "echo_personal_{customer_id}"
  - Collective bank (shared):    bank ID "echo_collective"

Retain format (section 6.2): distilled natural-language case notes, never raw
transcripts. Each note carries issue, environment, attempted fixes with results,
sentiment, and commitments with due dates.

Recall (section 6.3): personal recall returns the customer's own memories
(history, prior attempts, mood); collective recall returns anonymized patterns
(what's worked for this issue type on this plan/integration). Both are capped
to a handful of items so the prompt stays compact.

Degraded mode (section 7.3): if any Hindsight call times out or errors,
get_context returns a RecallResult with degraded=True. Never raises.

Uses Hindsight's async API (arecall, aretain, etc.) so it works correctly
inside an already-running asyncio event loop (e.g. FastAPI, agent loop).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from hindsight_client import Hindsight
from hindsight_client_api.exceptions import ApiException

from app.config import settings

logger = logging.getLogger("echo.memory")

COLLECTIVE_BANK = "echo_collective"
CUSTOMER_REGISTRY_BANK = "echo_customer_registry"


@dataclass
class MemoryCitation:
    memory_id: str
    text: str
    score: float = 0.0
    source: str = "personal"  # "personal" | "collective"


@dataclass
class RecallResult:
    citations: list[MemoryCitation] = field(default_factory=list)
    context_block: str = ""
    degraded: bool = False
    error: str | None = None


def _personal_bank_id(customer_id: str) -> str:
    return f"echo_personal_{customer_id}"


class MemoryService:
    def __init__(self) -> None:
        self._client = Hindsight(
            base_url=settings.hindsight_base_url,
            api_key=settings.hindsight_api_key,
            timeout=settings.hindsight_timeout_seconds,
        )

    # ------------------------------------------------------------------
    # Bank lifecycle (async)
    # ------------------------------------------------------------------

    async def _aensure_bank(self, bank_id: str, *, name: str, mission: str) -> None:
        try:
            await self._client.acreate_bank(bank_id=bank_id, name=name, mission=mission)
        except ApiException as e:
            if getattr(e, "status", None) in (400, 409):
                return  # bank already exists
            raise

    async def aensure_personal_bank(self, customer_id: str) -> str:
        bid = _personal_bank_id(customer_id)
        await self._aensure_bank(
            bid,
            name=f"Echo personal memory — {customer_id}",
            mission=(
                "Distilled case notes for a customer support context. "
                "Each note records the issue, environment, attempted fixes "
                "and their results, customer sentiment, and commitments "
                "with due dates. No raw transcripts."
            ),
        )
        return bid

    async def aensure_collective_bank(self) -> str:
        await self._aensure_bank(
            COLLECTIVE_BANK,
            name="Echo collective memory",
            mission=(
                "Anonymized support patterns across all customers. "
                "Stores only issue type, plan/integration context, "
                "which fixes worked or failed, and success rates. "
                "No personal identifiers, no customer names, no emails."
            ),
        )
        return COLLECTIVE_BANK

    async def _aensure_customer_registry(self) -> None:
        await self._aensure_bank(
            CUSTOMER_REGISTRY_BANK,
            name="Echo customer registry",
            mission=(
                "Customer profile records used only to populate the Echo demo UI. "
                "Do not use this bank as support conversation context."
            ),
        )

    async def arecord_customer_profile(self, profile: dict[str, Any]) -> bool:
        if not settings.hindsight_api_key:
            return False
        try:
            await self._aensure_customer_registry()
            metadata = {
                "record_type": "customer_profile",
                "id": str(profile["id"]),
                "name": profile["name"],
                "email": profile["email"],
                "company": profile["company"],
                "plan": profile["plan"],
                "integrations": ",".join(profile.get("integrations", [])),
                "created_at": profile["created_at"],
            }
            response = await asyncio.wait_for(
                self._client.aretain(
                    bank_id=CUSTOMER_REGISTRY_BANK,
                    content=f"Customer profile for {profile['name']} at {profile['company']}.",
                    metadata=metadata,
                    tags=["customer_profile", str(profile["id"])],
                ),
                timeout=settings.hindsight_timeout_seconds,
            )
            return bool(response.success)
        except Exception as e:
            logger.warning("arecord_customer_profile failed: %s", e)
            return False

    async def alist_customer_profiles(self) -> list[dict[str, Any]]:
        if not settings.hindsight_api_key:
            return []
        try:
            await self._aensure_customer_registry()
            response = await asyncio.wait_for(
                self._client.alist_memories(
                    bank_id=CUSTOMER_REGISTRY_BANK, limit=100
                ),
                timeout=settings.hindsight_timeout_seconds,
            )
            items = response.items if hasattr(response, "items") else []
            profiles = []
            for item in items:
                metadata = (
                    item.get("metadata") if isinstance(item, dict)
                    else getattr(item, "metadata", None)
                )
                if not isinstance(metadata, dict) or metadata.get("record_type") != "customer_profile":
                    continue
                profiles.append({
                    "id": metadata.get("id", ""),
                    "name": metadata.get("name", ""),
                    "email": metadata.get("email", ""),
                    "company": metadata.get("company", ""),
                    "plan": metadata.get("plan", ""),
                    "integrations": [
                        value for value in metadata.get("integrations", "").split(",") if value
                    ],
                    "created_at": metadata.get("created_at", ""),
                })
            return profiles
        except Exception as e:
            logger.warning("alist_customer_profiles failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # Recall (async)
    # ------------------------------------------------------------------

    async def aget_context(self, customer_id: str, query: str) -> RecallResult:
        """Recall personal + collective memories for the current message."""
        if not settings.hindsight_api_key:
            return RecallResult(degraded=True, error="Hindsight API key is not configured")
        citations: list[MemoryCitation] = []
        context_parts: list[str] = []

        personal_bank = _personal_bank_id(customer_id)
        personal_results = await self._asafe_recall(
            personal_bank, query, budget="mid"
        )
        if personal_results is not None:
            for r in personal_results[:5]:
                score = r.scores.final if r.scores else 0.0
                citations.append(
                    MemoryCitation(
                        memory_id=r.id, text=r.text, score=score, source="personal"
                    )
                )
                context_parts.append(f"[personal] {r.text}")
        else:
            coll_results = await self._asafe_recall(
                COLLECTIVE_BANK, query, budget="low"
            )
            if coll_results:
                for r in coll_results[:3]:
                    citations.append(
                        MemoryCitation(
                            memory_id=r.id,
                            text=r.text,
                            score=r.scores.final if r.scores else 0.0,
                            source="collective",
                        )
                    )
                    context_parts.append(f"[collective] {r.text}")
            return RecallResult(
                citations=citations,
                context_block="\n".join(context_parts),
                degraded=True,
                error="personal bank recall failed or timed out",
            )

        coll_results = await self._asafe_recall(COLLECTIVE_BANK, query, budget="low")
        if coll_results:
            for r in coll_results[:3]:
                citations.append(
                    MemoryCitation(
                        memory_id=r.id,
                        text=r.text,
                        score=r.scores.final if r.scores else 0.0,
                        source="collective",
                    )
                )
                context_parts.append(f"[collective] {r.text}")

        return RecallResult(
            citations=citations,
            context_block="\n".join(context_parts),
            degraded=False,
        )

    async def _asafe_recall(
        self, bank_id: str, query: str, *, budget: str = "mid"
    ) -> list[Any] | None:
        try:
            result = await asyncio.wait_for(
                self._client.arecall(bank_id=bank_id, query=query, budget=budget),
                timeout=settings.hindsight_timeout_seconds,
            )
            return list(result.results)
        except Exception as e:
            logger.warning("recall failed for bank %s: %s", bank_id, e)
            return None

    # ------------------------------------------------------------------
    # Retain (async)
    # ------------------------------------------------------------------

    async def arecord_interaction(self, customer_id: str, summary: str) -> str | None:
        if not settings.hindsight_api_key:
            return None
        bank_id = _personal_bank_id(customer_id)
        try:
            await self.aensure_personal_bank(customer_id)
            resp = await self._client.aretain(
                bank_id=bank_id,
                content=summary,
                tags=["case_note", customer_id],
            )
            if resp.success and resp.operation_ids:
                return resp.operation_ids[0]
            return None
        except Exception as e:
            logger.warning("arecord_interaction failed: %s", e)
            return None

    async def arecord_outcome(
        self, customer_id: str, issue: str, fix: str, worked: bool
    ) -> None:
        if not settings.hindsight_api_key:
            return
        note = (
            f"Issue type: {issue}. "
            f"Fix attempted: {fix}. "
            f"Outcome: {'resolved' if worked else 'failed'}. "
            "No personal identifiers stored."
        )
        try:
            await self.aensure_collective_bank()
            await self._client.aretain(
                bank_id=COLLECTIVE_BANK,
                content=note,
                tags=["outcome", issue, "resolved" if worked else "failed"],
            )
        except Exception as e:
            logger.warning("arecord_outcome failed: %s", e)

    # ------------------------------------------------------------------
    # Forget (async)
    # ------------------------------------------------------------------

    async def aforget(self, customer_id: str) -> None:
        if not settings.hindsight_api_key:
            return
        bank_id = _personal_bank_id(customer_id)
        try:
            await self._client.adelete_bank(bank_id=bank_id)
        except Exception as e:
            logger.warning("aforget failed: %s", e)

    # ------------------------------------------------------------------
    # List memories (async)
    # ------------------------------------------------------------------

    async def alist_memories(self, customer_id: str, limit: int = 10) -> list[Any]:
        if not settings.hindsight_api_key:
            return []
        bank_id = _personal_bank_id(customer_id)
        try:
            resp = await self._client.alist_memories(bank_id=bank_id, limit=limit)
            return list(resp.items) if hasattr(resp, "items") else []
        except Exception as e:
            logger.warning("alist_memories failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # Sync wrappers (for non-async callers — uses asyncio.run if no loop)
    # ------------------------------------------------------------------

    def get_context(self, customer_id: str, query: str) -> RecallResult:
        try:
            loop = asyncio.get_running_loop()
            # Already in an event loop — can't use asyncio.run, but shouldn't
            # be called from async code. Use thread to avoid deadlock.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run, self.aget_context(customer_id, query)
                ).result()
        except RuntimeError:
            return asyncio.run(self.aget_context(customer_id, query))

    def record_interaction(self, customer_id: str, summary: str) -> str | None:
        try:
            asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run, self.arecord_interaction(customer_id, summary)
                ).result()
        except RuntimeError:
            return asyncio.run(self.arecord_interaction(customer_id, summary))

    def forget(self, customer_id: str) -> None:
        try:
            asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run, self.aforget(customer_id)
                ).result()
        except RuntimeError:
            return asyncio.run(self.aforget(customer_id))


