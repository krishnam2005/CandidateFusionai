# CandidateFusion AI

**Multi-Source Candidate Data Transformer**
Deployed at: https://candidatefusionai-production.up.railway.app/
> A production-grade data transformation pipeline that ingests candidate information from multiple structured and unstructured sources, converts them into a single canonical profile, normalises data, intelligently merges conflicting information, assigns provenance and confidence, validates everything, and outputs configurable JSON.

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

---

## Table of Contents

- [Architecture](#architecture)
- [Folder Structure](#folder-structure)
- [Installation](#installation)
- [Usage](#usage)
  - [CLI](#cli)
  - [REST API \& Web UI](#rest-api--web-ui)
- [Input Sources](#input-sources)
- [Configuration](#configuration)
- [Source Priority \& Merge Rules](#source-priority--merge-rules)
- [Sample Output](#sample-output)
- [Edge Cases Handled](#edge-cases-handled)
- [Design Decisions](#design-decisions)
- [Tradeoffs](#tradeoffs)
- [Running Tests](#running-tests)
- [Future Improvements](#future-improvements)

---

## Architecture

### Pipeline Flow

```
Input Sources (CSV | ATS JSON | Resume PDF | GitHub URL | Notes TXT)
         │
         ▼
   Source Detection
         │
         ▼
   Extractors (Strategy Pattern — one per source)
         │
         ▼
   Canonical Mapper (ExtractedCandidate → Candidate)
         │
         ▼
   Normalization (Email | Phone | Skills | Dates | Location | URL)
         │
         ▼
   Merge Engine (Priority-based deterministic merge)
         │
         ▼
   Conflict Resolution (documented per field in provenance)
         │
         ▼
   Confidence Engine (source weights + agreement/disagreement)
         │
         ▼
   Provenance Engine (field-level lineage tracking)
         │
         ▼
   Validation Engine (schema | email | phone | dates | GPA | URLs)
         │
         ▼
   Projection Layer (configurable field selection + null handling)
         │
         ▼
   Output JSON
```

### Design Principles

| Principle | Application |
|-----------|-------------|
| **Clean Architecture** | Extraction → Normalization → Merge → Validation → Projection are fully decoupled layers |
| **SOLID** | Single responsibility per module; open for extension (new extractors), closed for modification |
| **Strategy Pattern** | All extractors implement `BaseExtractor`; the pipeline is agnostic to source type |
| **Factory Pattern** | `ExtractorFactory.create(SourceType)` instantiates extractors with proper DI |
| **Builder Pattern** | `CandidateProfileBuilder` assembles the final profile incrementally |
| **Dependency Injection** | `Pipeline` accepts all collaborators as constructor args; easily mocked in tests |
| **Repository Pattern** | Settings loaded via `get_settings()` singleton; never read `os.environ` directly |

---

## Folder Structure

```
candidate-fusion/
├── README.md
├── LICENSE
├── requirements.txt
├── pyproject.toml           # Ruff, Black, MyPy, Pytest, Coverage config
├── .env.example             # Environment variable template
├── .gitignore
├── main.py                  # Typer CLI entry point
│
├── config/
│   ├── settings.py          # Pydantic Settings — single config source of truth
│   ├── default.json         # Default output projection config
│   └── minimal.json         # Minimal field-set config (no provenance/metadata)
│
├── models/
│   ├── candidate.py         # Canonical domain models (Candidate, Experience, etc.)
│   ├── extracted.py         # Intermediate extraction result (ExtractedCandidate)
│   ├── confidence.py        # ConfidenceRecord, FieldConfidence
│   ├── provenance.py        # ProvenanceRecord, FieldProvenance
│   └── metadata.py          # PipelineMetadata, SourceType
│
├── extractors/
│   ├── base.py              # AbstractBaseExtractor + ExtractorError
│   ├── factory.py           # ExtractorFactory (Factory pattern)
│   ├── csv_extractor.py     # Recruiter CSV
│   ├── ats_json.py          # ATS JSON
│   ├── pdf_extractor.py     # Resume PDF (pdfplumber + PyMuPDF)
│   ├── github_extractor.py  # GitHub REST API
│   └── notes_extractor.py   # Recruiter Notes TXT
│
├── normalizers/
│   ├── text_normalizer.py      # Whitespace, capitalisation, deduplication
│   ├── email_normalizer.py     # RFC-compliant email normalisation
│   ├── phone_normalizer.py     # E.164 phone normalisation (phonenumbers)
│   ├── date_normalizer.py      # Flexible date parsing (dateutil)
│   ├── skill_normalizer.py     # Alias resolution + fuzzy matching (RapidFuzz)
│   ├── location_normalizer.py  # Structured location parsing
│   └── url_normalizer.py       # URL normalisation + platform detection
│
├── mergers/
│   └── merge_engine.py      # Deterministic multi-source merge engine
│
├── confidence/
│   └── engine.py            # Confidence scoring engine
│
├── validators/
│   └── validation_engine.py # Rule-based validation engine
│
├── projection/
│   └── projector.py         # Configurable output projection + JSON serialisation
│
├── services/
│   ├── canonical_mapper.py  # ExtractedCandidate → Candidate transformation
│   └── pipeline.py          # Main pipeline orchestrator
│
├── api/
│   ├── app.py               # FastAPI application factory (serves UI + API)
│   └── routes.py            # POST /api/v1/transform endpoint
│
├── ui/
│   └── index.html           # Minimal web UI (served at http://localhost:8000/)
│
├── utils/
│   ├── logging.py           # structlog configuration
│   ├── timer.py             # Execution timing utilities
│   └── retry.py             # Exponential backoff retry logic
│
├── inputs/                  # Sample input files
│   ├── recruiter.csv
│   ├── ats.json
│   └── notes.txt
│
├── outputs/                 # Pipeline output directory
│   ├── sample_output.json   # Default config output on sample inputs
│   └── candidate.json       # Full output with provenance
│
├── logs/                    # Structured log files
│
└── tests/
    ├── conftest.py          # Shared fixtures
    ├── unit/
    │   ├── test_normalizers.py
    │   ├── test_extractors.py
    │   ├── test_merge_engine.py
    │   ├── test_canonical_mapper.py
    │   ├── test_validators.py
    │   ├── test_confidence.py
    │   └── test_projector.py
    └── integration/
        ├── test_github_extractor.py  # GitHub API mocked
        └── test_pipeline.py          # End-to-end pipeline
```

---

## Installation

### Requirements

- Python 3.12+
- pip

### Quick Start

```bash
# Clone the repository
git clone https://github.com/<your-username>/candidate-fusion.git
cd candidate-fusion

# Create and activate virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment config and add your GitHub token (optional)
cp .env.example .env
```

> **GitHub Token (optional):** Add `GITHUB_TOKEN=ghp_...` to `.env` to get 5 000 req/hr instead of 60 unauthenticated. The pipeline works without it — GitHub will simply be skipped if the rate limit is hit.

---

## Usage

### CLI

Run the pipeline from the command line. At least one source flag is required.

```bash
# All three sample sources — default output config
python main.py \
  --csv inputs/recruiter.csv \
  --ats inputs/ats.json \
  --notes inputs/notes.txt \
  --output outputs/candidate.json

# Minimal output (fewer fields, no provenance/metadata)
python main.py \
  --csv inputs/recruiter.csv \
  --ats inputs/ats.json \
  --notes inputs/notes.txt \
  --config config/minimal.json \
  --output outputs/candidate_minimal.json

# ATS only — print to stdout
python main.py --ats inputs/ats.json

# With a GitHub profile
python main.py \
  --csv inputs/recruiter.csv \
  --github https://github.com/octocat

# Verbose logging (DEBUG level)
python main.py --ats inputs/ats.json --verbose

# Strict mode — exit code 2 on any validation error
python main.py --ats inputs/ats.json --strict
```

**CLI Options:**

| Option | Description |
|--------|-------------|
| `--csv` | Path to recruiter CSV file |
| `--ats` | Path to ATS JSON file |
| `--resume` | Path to resume PDF |
| `--github` | GitHub profile URL or username |
| `--notes` | Path to recruiter notes TXT |
| `--config` | Output configuration JSON (default: `config/default.json`) |
| `--output`, `-o` | Output file path (default: stdout) |
| `--verbose`, `-v` | Enable DEBUG logging |
| `--strict` | Exit code 2 on validation errors |

### REST API & Web UI

```bash
# Start the API server (from the project root)
uvicorn api.app:app --reload --port 8000
```

| URL | Description |
|-----|-------------|
| `http://localhost:8000/` | **Web UI** — drag-and-drop file uploads, live pipeline steps, tabbed profile view |
| `http://localhost:8000/docs` | Interactive Swagger docs |
| `http://localhost:8000/redoc` | ReDoc API reference |
| `http://localhost:8000/health` | Health check |

**POST `/api/v1/transform`** — `multipart/form-data`

```bash
curl -X POST http://localhost:8000/api/v1/transform \
  -F "ats_file=@inputs/ats.json" \
  -F "csv_file=@inputs/recruiter.csv" \
  -F "notes_file=@inputs/notes.txt" \
  | python -m json.tool
```

Fields: `csv_file`, `ats_file`, `resume_file`, `notes_file`, `github_url`, `config_file`. At least one is required.

---

## Input Sources

### Recruiter CSV (`--csv`)

Standard comma-separated file from a recruiter's spreadsheet.

Supported column names (case-insensitive):
- `first_name`, `last_name`, `full_name`
- `email`, `phone`
- `location`, `city`
- `current_title`, `current_company`
- `skills` (comma, semicolon, or pipe-delimited)
- `years_experience`
- `linkedin_url`, `github_url`
- `summary`

### ATS JSON (`--ats`)

Structured JSON from an ATS (Greenhouse, Lever, Workday, etc.).

Supports nested objects for `experience`, `education`, `projects`, `certifications`, and `social_links`. Field names are resolved with multiple aliases for cross-vendor compatibility.

See [`inputs/ats.json`](inputs/ats.json) for the full schema.

### Resume PDF (`--resume`)

PDF resume files.

- Primary extraction: `pdfplumber` (layout-preserving)
- Fallback: `PyMuPDF` (resilient on malformed PDFs)
- Parses sections: Experience, Education, Skills, Summary, Projects, Certifications
- Extracts: email, phone, LinkedIn URL, GitHub URL

### GitHub Profile (`--github`)

Fetches public profile data via the GitHub REST API v3.

- Set `GITHUB_TOKEN` in `.env` for 5 000 req/hr (vs 60 unauthenticated)
- Extracts: name, bio, location, email, repos (for skills), top projects

### Recruiter Notes (`--notes`)

Plain text or Markdown notes from a recruiter.

- Pattern-matches: email, phone, name, location, social links
- Keyword-scans for 500+ known technology skills
- Lowest confidence weight (0.70) — used as supplementary source

---

## Configuration

Output is controlled by a JSON configuration file passed via `--config`.

**`config/default.json`** — full output with provenance and metadata:

```json
{
  "output_fields": [
    "candidate_id", "full_name", "emails", "phones",
    "location", "skills", "experience", "education",
    "confidence", "provenance", "metadata"
  ],
  "include_provenance": true,
  "include_confidence": true,
  "include_metadata": true,
  "null_handling": "omit",
  "date_format": "ISO8601",
  "confidence_threshold": 0.0,
  "output_format": "json"
}
```

**`config/minimal.json`** — compact output for downstream consumers:

```json
{
  "output_fields": [
    "candidate_id", "full_name", "emails", "phones",
    "skills", "experience", "education"
  ],
  "include_provenance": false,
  "include_confidence": true,
  "include_metadata": false,
  "null_handling": "omit",
  "confidence_threshold": 0.5,
  "output_format": "json"
}
```

| Option | Values | Description |
|--------|--------|-------------|
| `output_fields` | `list[str]` | Fields to include in output |
| `include_provenance` | `bool` | Include full field-level provenance records |
| `include_confidence` | `bool` | Include confidence scores |
| `include_metadata` | `bool` | Include pipeline run metadata |
| `null_handling` | `omit` \| `null` \| `empty` | How to handle null values |
| `confidence_threshold` | `float` [0, 1] | Exclude fields below this confidence score |
| `output_format` | `json` | Output format (`jsonl` planned) |

---

## Source Priority & Merge Rules

| Source | Priority | Confidence Weight |
|--------|----------|-------------------|
| ATS    | 1 (highest) | 0.95 |
| CSV    | 2 | 0.92 |
| Resume | 3 | 0.90 |
| GitHub | 4 | 0.80 |
| Notes  | 5 (lowest) | 0.70 |

**Scalar fields** (name, summary, headline): winner = highest-priority source with a non-null value. Conflicts are recorded in provenance.

**Array fields** (skills, experience, education):
- Union across all sources
- Deduplication via RapidFuzz fuzzy matching (configurable threshold)
- Lower-priority sources enrich missing sub-fields

---

## Sample Output

The file [`outputs/sample_output.json`](outputs/sample_output.json) is the output produced by running the pipeline on the provided sample inputs (`inputs/recruiter.csv` + `inputs/ats.json` + `inputs/notes.txt`).

Abbreviated excerpt:

```json
{
  "candidate_id": "a1b2c3d4-...",
  "full_name": "Jane Smith",
  "emails": ["jane.smith@example.com", "j.smith@personal.io"],
  "phones": ["+14155550198"],
  "location": {
    "city": "San Francisco",
    "state": "CA",
    "country": "United States",
    "display": "San Francisco, CA, United States"
  },
  "skills": [
    { "name": "Python" },
    { "name": "FastAPI" },
    { "name": "Kubernetes" }
  ],
  "confidence": {
    "overall_score": 0.9242,
    "sources_used": ["ats", "csv", "notes"],
    "fields": {
      "full_name": { "score": 0.95, "explanation": "Base: 0.95 (source=ats)" },
      "emails":    { "score": 0.975, "explanation": "Base: 0.95 (source=ats) +0.05 (agreement)" }
    }
  },
  "metadata": {
    "pipeline_version": "1.0.0",
    "duration_ms": 342.7,
    "sources_succeeded": ["ats", "csv", "notes"],
    "sources_failed": [],
    "validation_passed": true
  }
}
```

---

## Edge Cases Handled

| Edge Case | Handling |
|-----------|----------|
| **Missing / garbage source** | Extractor catches all exceptions; run continues; `sources_failed` logged in metadata. Unknown values become `null`, never invented. |
| **Conflicting field values across sources** | Priority-based winner selected; conflict recorded as a `ProvenanceRecord` with both values and resolution method. |
| **Duplicate skills with variant names** | RapidFuzz `token_sort_ratio` deduplicates "Machine Learning" vs "ML" vs "machine-learning" via alias map + fuzzy threshold. |
| **Malformed / non-standard phone numbers** | `phonenumbers` library validates and normalises to E.164; unparseable numbers become `null` (not invented). |
| **PDF with no parseable text (image-only)** | pdfplumber attempt → PyMuPDF fallback → if still empty, extractor returns empty `ExtractedCandidate` and the source is marked failed. |
| **GitHub rate limit exceeded** | Caught as a transient error; run continues without GitHub data; warning logged. |

---

## Design Decisions

### Why pdfplumber + PyMuPDF (dual library)?

pdfplumber provides the best structure-preserving text extraction for well-formatted PDFs. PyMuPDF handles corrupt, image-heavy, or non-standard PDFs. Using both maximises extraction success across the diverse PDF formats encountered in production resume processing.

### Why RapidFuzz for skill matching?

3–10× faster than FuzzyWuzzy due to C++ implementation. `token_sort_ratio` handles word-order variation. Actively maintained with Python 3.12 wheels.

### Why orjson for serialisation?

3–5× faster than stdlib `json` for candidate-profile-sized objects. Native support for `datetime`, `UUID`, `date`, and `bytes`. Drop-in replacement.

### Why Pydantic v2 over dataclasses?

Automatic validation, type coercion, and serialisation. `extra="forbid"` catches typos in field names immediately. Significantly faster than v1.

### Why `structlog` over stdlib `logging`?

Machine-readable JSON output. Context propagation across async boundaries. Compatible with FastAPI/uvicorn's logging infrastructure.

### Why phonenumbers for phone normalisation?

The same library used by Google internally. Handles 250+ country dial codes and validates subscriber number ranges per country.

---

## Tradeoffs

| Decision | Alternative Considered | Reason for Choice |
|----------|----------------------|-------------------|
| Synchronous extractors | Async extractors | Simpler orchestration; GitHub API is the only I/O-bound extractor |
| Heuristic PDF parsing | spaCy NER model | Lower deployment complexity; NER can be plugged in via interface |
| In-process merge | Message queue | Simpler architecture for single-candidate; scales with worker pool |
| File-based config | Database config | Config-as-code is easier to version-control and review |
| Flat provenance list | Graph-based lineage | Sufficient for this use case; graph adds query complexity |
| Priority-based confidence | ML-based confidence | Deterministic and explainable without requiring training data |

---

## Running Tests

```bash
# Activate the virtual environment first
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

# All tests with coverage
pytest tests/ --cov=. --cov-report=term-missing -v

# Unit tests only (fast, no network)
pytest tests/unit/ -v

# Integration tests only
pytest tests/integration/ -v

# Specific module
pytest tests/unit/test_normalizers.py -v
```

---

## Future Improvements

- [ ] **Async pipeline** — Concurrent extractor execution with asyncio for significant latency reduction
- [ ] **NER-based resume parsing** — Fine-tuned spaCy model for higher-accuracy entity extraction from PDFs
- [ ] **Geocoding integration** — Optional geocoding API (Google Maps/Nominatim) behind the LocationNormalizer interface
- [ ] **Entity resolution** — Deduplication across multiple candidates in a batch run
- [ ] **Streaming output** — JSONL output for large batch processing
- [ ] **Plugin system** — Load extractor plugins from a directory without code changes
- [ ] **Caching layer** — Redis-based caching for GitHub API responses
- [ ] **Metrics** — Prometheus metrics endpoint for pipeline throughput and error rates
- [ ] **ML confidence** — Replace weight-based confidence with a model trained on labelled merge outcomes

---

## License

MIT License — see [LICENSE](LICENSE).
