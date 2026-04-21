# Legacy-to-Modern Code Migration with SDGs and LLMs

This repository contains a working prototype for migrating legacy `C` code toward `Rust` by combining:

- static dependency analysis over the full repository,
- an SDG-style graph representation of code relationships,
- and dependency-safe topological orchestration with repeated LLM calls.

The current implementation includes Phase 1 (analysis and graph generation) and a simplified Phase 2 execution runtime that repeatedly calls an LLM per function in dependency order.

## Objectives

1. Build a repository-wide dependency model that captures:
   - function definitions and calls,
   - include relationships,
   - global variable reads and writes,
   - and type usage links.
2. Use that model as the foundation for dependency-safe migration planning where code changes can be propagated in dependency order.

## Tech Stack

- Source language: `C`
- Target language (planned): `Rust`
- Parser: `tree-sitter-c`
- Graph engine: `networkx`
- Frontend: `React + TypeScript + Vite + Cytoscape`

## Repository Layout

- `phase1/` - Python pipeline for parsing C code and generating graph artifacts.
- `phase2/` - Topological execution pipeline with repeated LLM calls (`mock` or `llm` runtime).
- `repo/` - Pilot C codebase used as controlled input for analysis.
- `artifacts/phase1/` - Generated JSON artifacts from the Phase 1 pipeline.
- `artifacts/phase2/` - Generated JSON artifacts from the Phase 2 pipeline.
- `frontend/` - Visual UI to inspect symbols and dependency topology.
- `tests/` - Pytest suite for analysis correctness and regression checks.

## Prerequisites

Install the following on your machine:

- Python 3.10+
- Node.js 18+ and npm
- GCC/Clang and `make` (for building the pilot C repo)

Install Python dependencies used by the current code:

```bash
python3 -m pip install networkx tree-sitter tree-sitter-c pytest
```

## How to Run This Repository

### 1) Build and run the pilot C repository

```bash
cd repo
make
make run
```

Optional cleanup:

```bash
cd repo
make clean
```

### 2) Generate Phase 1 SDG artifacts

From the project root:

```bash
python3 -m phase1 --repo repo --out artifacts/phase1
```

This command generates:

- `artifacts/phase1/symbol_table.json`
- `artifacts/phase1/call_graph.json`
- `artifacts/phase1/include_graph.json`
- `artifacts/phase1/sdg_v1.json`
- `artifacts/phase1/function_analysis.json`
- `artifacts/phase1/unresolved_calls.json`
- `artifacts/phase1/report.json`

### 3) Run the test suite

From the project root:

```bash
python3 -m pytest tests -q
```

### 4) Run Phase 2 orchestration

Generate Phase 2 outputs with deterministic mock runtime:

```bash
python3 -m phase2 --repo repo --sdg artifacts/phase1/sdg_v1.json --out artifacts/phase2 --runtime mock
```

Run with Groq provider:

```bash
export GROQ_API_KEY="<your_key>"
python3 -m phase2 \
  --repo repo \
  --sdg artifacts/phase1/sdg_v1.json \
  --out artifacts/phase2 \
  --runtime llm \
  --llm-provider groq \
  --llm-model llama-3.3-70b-versatile
```

Run with Ollama provider:

```bash
python3 -m phase2 \
  --repo repo \
  --sdg artifacts/phase1/sdg_v1.json \
  --out artifacts/phase2 \
  --runtime llm \
  --llm-provider ollama \
  --llm-model llama3.1 \
  --llm-base-url http://localhost:11434/v1
```

By default, the orchestrator logs progress for every call (current call, calls left, and percent complete). Tune verbosity with `--log-level`.

## How to Run the Frontend

The frontend reads SDG artifacts from `frontend/public/artifacts/`.

If you generated new artifacts in `artifacts/phase1/`, sync them first:

```bash
mkdir -p frontend/public/artifacts
cp -R artifacts/phase1/. frontend/public/artifacts/
```

Start the frontend in development mode:

```bash
cd frontend
npm install
npm run dev
```

Open the local URL shown by Vite (usually `http://localhost:5173`).

### Production build and preview

```bash
cd frontend
npm run build
npm run preview
```

## Current Status

- Phase 1 parsing and artifact generation is implemented.
- Query and impact analysis utilities are available in `phase1/pipeline.py`.
- Phase 2 topological orchestration is implemented with per-function repeated LLM calls.
- Frontend visualization is wired to SDG JSON artifacts.
- LLM runtime supports `groq` and `ollama` providers.

## Troubleshooting

- If the frontend loads but graph data is empty, verify `frontend/public/artifacts/sdg_v1.json` exists.
- If Python module imports fail, reinstall the Python dependencies listed above.
- If `make` fails in `repo/`, ensure your compiler toolchain is installed and available in `PATH`.
