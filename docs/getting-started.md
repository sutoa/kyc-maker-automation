# Getting Started

This guide walks you through running your first KYC document processing workflow end to end — from installing dependencies to downloading the compliance report.

## Prerequisites

- **Python 3.11 or later** — check with `python --version`
- **An LLM API key** — either an OpenAI key (`sk-...`) or a Google key for Gemini; at least one is required
- **pip** — bundled with Python 3.11+

## Step 1: Install dependencies

```bash
# Clone the repo (or navigate to your local copy)
cd kyc-maker-automation

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install runtime dependencies
pip install -r requirements.txt
```

## Step 2: Configure environment

```bash
cp .env.example .env
```

Open `.env` and set your API key. For OpenAI (the default):

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-key-here
```

For Google Gemini:

```bash
LLM_PROVIDER=gemini
GOOGLE_API_KEY=your-google-key-here
```

All other variables have sensible defaults for local development — you do not need to change them for a first run.

## Step 3: Initialise the database

```bash
python -c "from src.services.database import init_db; init_db()"
```

This creates `kyc_workflows.db` in the project root with the required tables.

## Step 4: Start the API server

```bash
uvicorn src.api.main:app --reload --port 8000
```

You should see:

```
INFO:     Starting KYC Document Processing API...
INFO:     Database initialized.
INFO:     Workflow compiled from YAML config.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

The interactive API docs are now at `http://localhost:8000/api/v1/docs`.

## Step 5: Upload documents

```bash
curl -X POST http://localhost:8000/api/v1/workflows \
  -F "files=@/path/to/your-kyc-document.pdf"
```

You can upload multiple files in one request:

```bash
curl -X POST http://localhost:8000/api/v1/workflows \
  -F "files=@ownership_register.pdf" \
  -F "files=@articles_of_incorporation.pdf"
```

Save the `workflow_id` from the response — you will need it in the next steps.

## Step 6: Start processing

```bash
curl -X POST http://localhost:8000/api/v1/workflows/<workflow_id>/start
```

The pipeline runs asynchronously. You can follow progress via the WebSocket (requires a WebSocket client like `wscat`):

```bash
# Install wscat if needed: npm install -g wscat
wscat -c ws://localhost:8000/ws/workflows/<workflow_id>
```

Or simply poll the status endpoint:

```bash
watch -n 2 curl -s http://localhost:8000/api/v1/workflows/<workflow_id>
```

## Step 7: Download the report

Once status is `"completed"`:

```bash
curl -o report.json \
  http://localhost:8000/api/v1/workflows/<workflow_id>/output
```

The report is a JSON file containing all extracted persons classified as CSM or NON_CSM, with titles, source documents, and page references for each entry.

## Common first-run errors

| Error | Cause | Fix |
|---|---|---|
| `AuthenticationError: Incorrect API key` | `OPENAI_API_KEY` is wrong or not set | Check `.env` — no quotes around the key value |
| `ModuleNotFoundError: No module named 'langgraph'` | Dependencies not installed | Run `pip install -r requirements.txt` inside the activated venv |
| `OperationalError: no such table: workflow_runs` | Database not initialised | Run `python -c "from src.services.database import init_db; init_db()"` |
| `422 Unprocessable Entity` on upload | File type not supported or file too large | Only PDF and TXT files are accepted; default size limit is 50 MB |
| Workflow stuck in `in_progress` for >10 minutes | LLM rate limit or timeout | Check server logs; the extractor retries up to 4 times automatically |

<!-- generated-by: project-docs-skill -->
