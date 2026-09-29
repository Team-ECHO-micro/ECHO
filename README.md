# Echo: Memory-First AI Customer Support Agent

The React frontend talks to a local FastAPI backend. Hindsight stores customer profiles and support memories; Groq generates chat replies. There is no Supabase or SQL database dependency. The three demo customers are backend fixtures.

## Run the backend

Copy `backend/.env.example` to `backend/.env` and set `HINDSIGHT_API_KEY` and `GROQ_API_KEY`. Then, in a terminal:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

## Run the frontend

In a second terminal, from the project root:

```powershell
npm install
npm run dev
```

The frontend uses `http://127.0.0.1:8000` by default. Set `VITE_API_URL` in a root `.env.local` file to use a different backend URL.

Customer profiles and support memories are stored in Hindsight. Without `HINDSIGHT_API_KEY`, demo profiles still load, but customer creation and memory operations are unavailable. Chat replies also require `GROQ_API_KEY`.

## API contract (section 9)

| Method | Route | Purpose |
|--------|-------|---------|
| GET  | /api/health | Health + config status |
| GET  | /api/customers | List customers |
| GET  | /api/customers/{id} | Get one customer |
| POST | /api/chat | SSE chat stream |
| GET  | /api/customers/{id}/brief | Handoff brief |
| POST | /api/customers/{id}/time-jump | Advance virtual clock |
| POST | /api/customers/{id}/outcome | Record fix outcome |
| DELETE | /api/customers/{id}/memory | Forget customer memory |
| POST | /api/eval/run | Run evaluation scenarios |
