# FlowForge BPM

Pega-inspired business process management portfolio project built using React, FastAPI and SQLite. A local, synthetic-data demo of case orchestration, decision rules, and approval gates.

## Features

- Case creation, queue, filtering, dashboard metrics and lifecycle actions
- Workflow Studio: add, rename and drag to reorder stages
- Approval decision table: amount threshold controls approval routing
- Configurable SLA deadline with overdue indicator
- Workflow snapshot per case, so existing cases retain their original routing
- Approval/rejection validation and chronological audit history
- Deterministic case summaries (not an AI model yet)
- OpenAPI documentation and automated test workflow

## Quick start on Windows

Install Python 3.12 and Node.js 22 or later. From the repository folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. API docs are at http://127.0.0.1:8000/docs.

## Demo workflow

Create a synthetic purchase request for $2,000. Advance from Submitted to Review to Approval, then approve. Review the chronological audit log. A request below $1,000 skips Approval by default. Edit thresholds and SLA in Decision Rules and Workflow Studio.

## Architecture

React UI → FastAPI endpoints → transactional SQLite case engine → audit records. Configuration changes apply to newly created cases, and each case captures its own stage sequence and SLA deadline.

## Tests

`python -m pytest -q`

## Limitations and next steps

This is not a production BPM platform, a clone of Pega, or a validated enterprise system. The actor name is demo input, not authentication or enforced roles; audit records are not tamper-proof. Bind only to localhost and use synthetic data. Next steps: authentication and RBAC, PostgreSQL migrations, authenticated actor identity, parallel paths, SLA notifications, local LLM-assisted case summarization, and deployment to an approved environment.
