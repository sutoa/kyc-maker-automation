# Quickstart: KYC Document Processing

**Date**: 2025-03-22
**Feature**: 001-kyc-document-processing

## Prerequisites

- Python 3.11+
- Access to OpenAI API or Google Gemini API
- Sample HandelsRegister PDF documents for testing

## Installation

```bash
# Clone repository
git clone <repository-url>
cd kyc-maker-automation

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Configuration

### 1. Environment Variables

Create a `.env` file in the project root:

```bash
# LLM Provider Configuration
LLM_PROVIDER=openai  # or "gemini"

# OpenAI (if LLM_PROVIDER=openai)
OPENAI_API_KEY=sk-...

# Gemini (if LLM_PROVIDER=gemini)
GOOGLE_API_KEY=...

# Application Settings
DATABASE_URL=sqlite:///./kyc_workflows.db
UPLOAD_DIR=./uploads
LOG_LEVEL=INFO
```

### 2. Verify Agent Configuration

Agent definitions are in `src/config/agents.yaml`. Review and customize prompts in `src/prompts/`.

## Running the Application

### Start the API Server

```bash
# Development mode with auto-reload
uvicorn src.api.main:app --reload --port 8000

# Production mode
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`.

### API Documentation

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Basic Usage

### 1. Upload Documents and Create Workflow

```bash
curl -X POST http://localhost:8000/api/v1/workflows \
  -F "files=@handelsregister_example.pdf"
```

Response:
```json
{
  "workflow_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "documents": [
    {"filename": "handelsregister_example.pdf", "file_type": "PDF", "page_count": 5}
  ]
}
```

### 2. Start Processing

```bash
curl -X POST http://localhost:8000/api/v1/workflows/550e8400.../start
```

### 3. Monitor Progress (WebSocket)

Connect to WebSocket for real-time updates:

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/workflows/550e8400...');
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Event:', data.event, data.data);
};
```

### 4. Check Status

```bash
curl http://localhost:8000/api/v1/workflows/550e8400...
```

### 5. Download Results

```bash
curl -o output.json http://localhost:8000/api/v1/workflows/550e8400.../output
```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test categories
pytest tests/unit/          # Unit tests
pytest tests/contract/      # Agent contract tests
pytest tests/integration/   # Integration tests
```

## Sample Workflow Output

```json
{
  "workflow_id": "550e8400-e29b-41d4-a716-446655440000",
  "completed_at": "2025-03-22T10:32:45Z",
  "document_manifest": [
    {
      "filename": "handelsregister_example.pdf",
      "file_type": "PDF",
      "page_count": 5,
      "processing_status": "processed"
    }
  ],
  "csm_list": [
    {
      "first_name": "Hans",
      "last_name": "Müller",
      "job_title": "Geschäftsführer",
      "classification": "CSM",
      "reasoning": "Individual holds position of Geschäftsführer (Managing Director)...",
      "source_references": [
        {"document": "handelsregister_example.pdf", "page": 2}
      ]
    }
  ],
  "non_csm_list": [...]
}
```

## Troubleshooting

### LLM Service Unavailable

If you see `LLM_SERVICE_UNAVAILABLE` errors:
- Verify your API key is correct in `.env`
- Check the provider status (OpenAI/Google)
- The system will retry 3 times with exponential backoff automatically

### Extraction Issues

If extraction quality is poor:
- Ensure documents are text-based PDFs (not scanned images)
- For scanned documents, OCR preprocessing may be needed
- Check the `prompts/extractor.md` prompt for language-specific issues

### German Character Encoding

The system handles German characters (ä, ö, ü, ß) automatically. If you see encoding issues:
- Ensure input files are UTF-8 encoded
- Check that your terminal/shell supports UTF-8

## Next Steps

1. Review the [API Documentation](./contracts/api.md) for all endpoints
2. Customize agent prompts in `src/prompts/` for your specific CSM definition
3. Add sample HandelsRegister documents to `tests/fixtures/` for testing
4. Configure the observability UI (see User Story 5/6)

## Project Structure

```
src/
├── agents/          # Agent implementations
├── api/             # FastAPI application
├── config/          # YAML configurations
├── core/            # LLM abstraction, workflow engine
├── models/          # Pydantic data models
├── prompts/         # External prompt files
└── services/        # Business logic services

tests/
├── contract/        # Agent input/output tests
├── integration/     # Multi-agent workflow tests
├── unit/            # Individual function tests
└── fixtures/        # Sample documents
```
