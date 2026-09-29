# Echo — 3-Minute Demo Script

> Target time: **3 minutes**. Practice until the sequence flows naturally without improvisation.

---

## Pre-demo Checklist

- [ ] Backend running on port 8000 with valid `GROQ_API_KEY` and `HINDSIGHT_API_KEY`
- [ ] Frontend running on port 5173
- [ ] Click **Reset** in the header to start from a clean state
- [ ] Select **Priya Nair** in the sidebar

---

## Sequence

### 0:00 – 0:30 · Setup & Memory OFF (30s)

1. **Make sure Memory is OFF** (toggle in top-right should say "Memory OFF")
2. Click **Load ticket history** in the sidebar to seed Priya's case notes
3. Type or click the suggested message:
   > "The webhook issue is back again. We're seeing the same delivery failures as last time."
4. **Point out:** Echo responds generically — asks for details it should already know, might suggest regenerating the signing token (the same fix that already failed)

### 0:30 – 1:15 · Memory ON (45s)

5. **Toggle Memory ON** (top-right button)
6. Send the same message again:
   > "The webhook issue is back again. We're seeing the same delivery failures as last time."
7. **Point out the difference:**
   - Echo acknowledges Priya by context ("I see the webhook issue is back")
   - Echo does NOT suggest regenerating the signing token (already failed)
   - Sentiment is detected as `frustrated`
   - The transparency panel shows which memories were recalled and their scores
8. **Click "Transparency"** panel if not visible — show recalled memories and their sources (personal vs collective)

### 1:15 – 1:45 · Time Jump & Overdue Commitments (30s)

9. In the **Time Jump** panel (sidebar), set days to `30` and click **Jump**
10. **Point out:**
    - The virtual clock advances (visible in the header)
    - Overdue commitments appear in the sidebar with red badges showing days overdue
    - The commitment "Follow up after the Friday release to confirm webhook stability" is now flagged as overdue
11. Click **Handoff brief** — show that the brief also highlights overdue commitments

### 1:45 – 2:15 · Forget & Fresh Start (30s)

12. Click **Forget all** in the sidebar
13. Send the message again:
    > "The webhook issue is back again."
14. **Point out:** Without memory, Echo behaves as if meeting Priya for the first time — no context, no history, generic response
15. This proves the memory system is real, not hardcoded

### 2:15 – 2:45 · Evaluation Results (30s)

16. Click the **Eval** button in the header
17. Click **Run All Scenarios**
18. **Point out the summary cards:**
    - Average memories recalled with Memory ON vs OFF
    - Individual scenario results showing the agent's responses
    - The clear difference in context-awareness between ON and OFF

### 2:45 – 3:00 · Wrap-up (15s)

19. Summarise the key takeaway:
    > "Echo proves that memory-first support is practical today. With Hindsight for memory and Groq for generation, we get context-aware replies that never ask what they already know, never repeat failed fixes, and track commitments — all with full transparency."

---

## Backup Notes

- **If Groq is slow:** The agent has a fallback model; just wait a moment.
- **If Hindsight is unreachable:** The UI shows a "Memory degraded" badge — Echo still works, just without context. This demonstrates graceful degradation.
- **Demo reset:** Click the **Reset** button anytime to return to the starting state.
- **Virtual clock file:** Persisted at `backend/virtual_clock.json` — deleted on reset.
