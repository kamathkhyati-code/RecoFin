# ADR 0001: Core Tech Stack for Agentic Recon

**Status:** Accepted
**Date:** 2026-07-08

## Context
Re-architecting the deterministic recon pipeline into a LangGraph multi-agent system with 3 interns working in parallel (data agents, reasoning agents, platform).

## Decision
- **Language:** Python 3.11+ (developed on 3.14)
- **Orchestration:** LangGraph (stateful agent graph, checkpointer for resumability)
- **Validation/typing:** Pydantic v2 (typed I/O + guardrails)
- **Vector store:** Chroma (match memory / semantic matching)
- **Testing:** pytest
- **Lint/format:** ruff + black
- **Repo layout:** single monorepo, flat layout, 3 top-level packages (datagents, reasoning, recon_platform), one shared pyproject.toml

## Consequences
- All three interns install the same editable package (`pip install -e ".[dev]"`) from repo root.
- Version pins live in one place; upgrades require a single PR reviewed by all three.
