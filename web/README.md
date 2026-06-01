# MAF Risk Assessment — Web UI

React + Vite frontend for the Microsoft Agent Framework (MAF) loan
risk-assessment workflow. Streams stage-by-stage results from
`POST /workflows/risk/stream` (SSE) on the FastAPI server.

## Develop

```bash
# 1. Start the workflow API (in repo root)
pip install agent-framework        # Microsoft Agent Framework (RC available)
uv run uvicorn loan_processor.workflow_api:app --port 8001 --reload

# 2. Start the UI (in web/)
npm install
npm run dev
# open http://localhost:5173
```

The Vite dev server proxies `/api/*` → `http://127.0.0.1:8001`.
For production builds, set `VITE_WORKFLOW_API_URL` to the deployed URL.
