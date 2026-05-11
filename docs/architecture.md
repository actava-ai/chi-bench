# chi-Bench Architecture

## Components

```
┌──────────────────────────────────────────────────────────────┐
│           chi-bench:latest (single image)                    │
│                                                              │
│   ┌─────────────────┐    ┌────────────────────────────────┐  │
│   │  Agent harness  │    │  chi-bench serve               │  │
│   │  (codex,        │◄──►│   • FastAPI :8023              │  │
│   │   claude-code,  │    │   • provider MCP :8020         │  │
│   │   openclaw, ...)│    │   • payer MCP :8100            │  │
│   └─────────────────┘    │   • CM MCP :8200               │  │
│                          └────────────────────────────────┘  │
│                                                              │
│   ┌─────────────────┐                                        │
│   │  Verifier       │ ──► writes /logs/artifacts/...         │
│   │  (WorkspaceJudge│                                        │
│   │   on Claude     │                                        │
│   │   Opus 4.7)     │                                        │
│   └─────────────────┘                                        │
└──────────────────────────────────────────────────────────────┘
```

## Layers (`src/chi_bench/`)

- **core/** — domain models (`PriorAuthCase`, `CMOutreachTask`, ...), state machines, world store.
- **services/** — ~29 HTTP/MCP-backed domain services (chart, coverage, intake, p2p, ...).
- **server/** — FastAPI app exposing the services as REST endpoints under `/api/...`.
- **mcp/** — three MCP servers wrapping the services (provider, payer, CM).
- **conversation/** — patient simulator + P2P-session orchestration.
- **verifier/** — pluggable judge (WorkspaceJudge by default) + per-stage rubrics.
- **experiment/** — Harbor-driven trial runner + 7 agent harnesses + `dual-pa-e2e`.

## Trial lifecycle

1. `chi-bench experiment run -f <config>` shells out to Harbor.
2. Harbor spawns one container per trial via `ChiBenchDockerEnvironment` (or `ChiBenchModalEnvironment` for `-e modal`).
3. The container entrypoint:
   - reads `CHI_BENCH_TASK_ID`, wires `/opt/chi-bench/tasks/<task_id>/fixtures` → `/fixtures`;
   - starts the unified server (HTTP + 3 MCP threads);
   - waits for all four endpoints to accept traffic;
   - exec's the agent harness's CLI.
4. Agent harness runs the agent against the MCP tools.
5. After the agent stops (success / timeout / abstain), Harbor invokes the verifier in the same container.
6. Verifier writes `verifier/scorecard.json` and `verifier/verdicts.json`; Harbor produces `result.json`.

## Why the LLM judge needs Anthropic credits

The verifier always uses `claude-opus-4-7` (configurable but paper-faithful default).
See `docs/judge.md`.
