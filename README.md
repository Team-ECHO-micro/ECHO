# Echo: Memory-First AI Customer Support Agent

Echo is an AI-powered customer support agent that remembers every interaction. Unlike traditional support tools that forget context between conversations, Echo uses a two-tier memory system (personal + collective) to recognize returning customers, avoid repeating failed fixes, honour commitments, and adapt its tone to the customer's emotional state.

**Built with:** React + Vite (frontend), FastAPI (backend), [Hindsight](https://hindsight.vectorize.io/) (memory), [Groq](https://groq.com/) (LLM inference).

---

## Architecture

```
┌──────────────┐       POST /api/chat (SSE)       ┌───────────────┐
│  React + Vite │──────────────────────────────────▶│   FastAPI      │
│  (port 5173)  │◀──────── event stream ──────────│   (port 8000)  │
└──────────────┘                                   └───┬───────┬───┘
                                                       │       │
                                 recall / retain ──────┘       └────── generate
                                                       ▼               ▼
                                              ┌─────────────┐  ┌────────────┐
                                              │  Hindsight   │  │   Groq     │
                                              │  (memory)    │  │   (LLM)    │
                                              └─────────────┘  └────────────┘
```

### Two-tier memory

| Bank | Purpose |
|------|---------|
| **Personal** (`echo_personal_{id}`) | Distilled case notes for one customer — issues, fixes tried, sentiment, commitments |
| **Collective** (`echo_collective`) | Anonymized patterns — which fixes work for which issue types across all customers |

### Key features

- **Context-aware replies** — Never asks for information it already knows
- **Failed-fix avoidance** — Tries a different approach when a prior fix didn't work
- **Sentiment detection** — Apologises and prioritises when a customer is frustrated
- **Commitment tracking** — Tracks follow-up promises with due dates
- **Virtual clock & overdue detection** — Advance time during demos to show overdue commitments
- **Transparency panel** — Shows which memories were recalled and how they influenced the reply
- **Handoff briefs** — Generates context-rich handoff documents for human agents
- **Graceful degradation** — Works without memory when Hindsight is unavailable
- **Evaluation harness** — 8 automated scenarios comparing Memory OFF vs Memory ON

---

## Required Keys

| Variable | Source | Required for |
|----------|--------|--------------|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com/) | Chat replies (LLM generation) |
| `HINDSIGHT_API_KEY` | [hindsight.vectorize.io](https://hindsight.vectorize.io/) | Memory recall, retain, forget |

Without `GROQ_API_KEY`, chat will fail. Without `HINDSIGHT_API_KEY`, demo customers still load from fixtures but memory operations are unavailable.

---

## Setup & Run

### 1. Clone

```powershell
git clone https://github.com/Team-ECHO-micro/ECHO.git
cd ECHO
```

### 2. Backend

```powershell
cd backend
copy .env.example .env
# Edit .env and set GROQ_API_KEY and HINDSIGHT_API_KEY

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

### 3. Frontend

In a **second terminal** from the project root:

```powershell
npm install
npm run dev
```

The frontend runs on `http://localhost:5173` and proxies API calls to `http://127.0.0.1:8000`. To change the backend URL, create a `.env.local` file at the project root:

```
VITE_API_URL=http://your-backend-url:8000
```

---

## API Routes

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/api/health` | Health check + config status + virtual clock |
| GET | `/api/customers` | List all customers (fixtures + Hindsight) |
| GET | `/api/customers/{id}` | Get one customer |
| POST | `/api/customers` | Create a new customer |
| POST | `/api/chat` | SSE chat stream (agent loop) |
| POST | `/api/customers/{id}/seed-memory` | Seed demo case notes into Hindsight |
| GET | `/api/customers/{id}/memories` | List stored memories for a customer |
| GET | `/api/customers/{id}/brief` | Generate handoff brief with overdue flags |
| GET | `/api/virtual-clock` | Get current virtual clock time |
| POST | `/api/customers/{id}/time-jump` | Advance virtual clock and return overdue commitments |
| POST | `/api/customers/{id}/outcome` | Record whether a fix worked or failed |
| DELETE | `/api/customers/{id}/memory` | Forget all memory for a customer |
| POST | `/api/eval/run` | Run evaluation scenarios (8 workflows) |
| POST | `/api/demo/reset` | Reset clock, memories, and eval results |

---

## Demo Reset

To return the system to a clean starting state before a demo:

**Via UI:** Click the **Reset** button in the header.

**Via API:**
```bash
curl -X POST http://localhost:8000/api/demo/reset
```

This resets the virtual clock, wipes all demo customer memories, and removes any saved evaluation results.

---

## Evaluation

The evaluation harness tests 8 scenarios:

1. **repeat_issue** — Customer raises the same issue twice
2. **return_after_gap** — Customer returns after a long gap
3. **failed_fix_avoidance** — Agent must not re-suggest a failed fix
4. **overdue_commitment** — A follow-up promise is past due
5. **frustrated_customer** — Customer is clearly frustrated
6. **new_customer** — No prior history at all
7. **memory_off_vs_on** — Same message with memory OFF then ON
8. **forget** — After memory wipe, agent treats customer as new

**Via UI:** Click the **Eval** button in the header, then **Run All Scenarios**.

**Via API:**
```bash
curl -X POST http://localhost:8000/api/eval/run \
  -H "Content-Type: application/json" \
  -d '{"memory_on": true}'
```

Results are saved as JSON in `backend/eval_results/`.

---

## Virtual Clock & Time Jump

The virtual clock starts at `2026-01-01T09:00:00+00:00` (configurable via `VIRTUAL_NOW` in `.env`). During demos, advance it to make commitments overdue:

**Via UI:** Use the **Time Jump** panel in the sidebar — enter the number of days and click **Jump**.

**Via API:**
```bash
curl -X POST http://localhost:8000/api/customers/{id}/time-jump \
  -H "Content-Type: application/json" \
  -d '{"days": 30}'
```

The response includes overdue commitments with `days_overdue` counts.

---

## Project Structure

```
ECHO/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── agent.py        # Agent loop: recall → prompt → generate → retain
│   │   ├── config.py       # Settings + VirtualClock
│   │   ├── eval.py         # 8-scenario evaluation harness
│   │   ├── main.py         # FastAPI routes
│   │   └── memory.py       # Hindsight MemoryService wrapper
│   ├── .env.example
│   ├── requirements.txt
│   └── test_phase2.py      # End-to-end integration test
├── src/
│   ├── App.tsx             # Main React UI
│   ├── lib/
│   │   ├── api.ts          # API client functions
│   │   └── icons.ts        # Icon exports
│   ├── index.css
│   └── main.tsx
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tsconfig.app.json
├── tsconfig.node.json
├── tailwind.config.js
├── postcss.config.js
├── eslint.config.js
└── DEMO.md                 # 3-minute demo script
```
