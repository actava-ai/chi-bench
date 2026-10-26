# chi-Bench Harbor exports

New exports from this checkout use Harbor 0.20.0's native separate-verifier flow.
The exporter creates a clean agent image, a trusted simulator sidecar, and a
separate verifier image. Generated tasks use schema version 1.2 and preserve the
source domain and agent and verifier timeout values.

An existing published Hub archive retains the build definitions included in
that release. Updating this exporter does not replace a published task archive.
Use a newly exported package to obtain this layout; do not infer that an older
`actava-ai/chi-bench@<tag>` archive has these isolation properties.

## Runtime flow

1. Harbor builds the `agent` and `simulator` targets in
   `environment/Dockerfile`. The trusted targets fetch chi-Bench source and the
   dataset at build time. The agent target starts from the shared toolchain
   base and copies only its runner modules and dependencies. Claude Code
   defaults to version `2.1.219` through `CLAUDE_CODE_VERSION`.
2. The simulator downloads the gated handbook with `HF_TOKEN`, starts the HTTP
   and MCP servers, and publishes regular copies of the public instructions,
   tool reference, and handbook. Its health check requires the public-assets
   ready marker. Main starts after the simulator becomes healthy.
3. Main shares the simulator's network namespace and the workflow workspace at
   `/logs/artifacts/workspaces`. Public assets are mounted read-only. The raw
   artifact mount exposes only `/srv/chi-bench/raw/artifacts` at
   `/agent-raw/artifacts:ro`; the raw chart database remains in the simulator.
   New-referral provider tasks omit the agent's raw-artifact mount.
4. In separate-verifier mode, Harbor requests that main stop before running simulator collection hooks. The trusted simulator alone has a Docker socket mount for checking its own Compose project's main-container status. The collector requires exactly one stopped main, closes tool admission, waits for already admitted work to finish, and snapshots authenticated `/export` into `/logs/artifacts/final-state.json`. It checks main's stopped state again before accepting the snapshot.
5. Harbor collects the frozen state, workspaces, and public handbook from the
   simulator. These entries have distinct host destinations under `trusted/`.
   The main publish-directory entry excludes the workspace and frozen-state
   names. The control token is outside every artifact and shared mount.
6. Harbor builds a separate container from `tests/Dockerfile`, using the trusted
   `verifier` target with an empty entrypoint. It restores collected files at
   their original source paths, including `/logs/artifacts/workspaces`, and
   runs `/tests/test.sh`. This container does not bootstrap a simulator.
   Standard and Marathon verifiers both require `--exported-state-input`.
   A missing, empty, invalid, or unconfirmed frozen-state file prevents scoring. The verifier requires the collector's stopped-main proof.

Harbor 0.20.0 treats stop and collect-hook failures as warnings. The trusted collector therefore checks Docker's actual container state independently. A running main, unavailable Docker status, ambiguous container identity, or unfinished admitted call leaves no accepted snapshot. An older snapshot is removed before collection starts. The generated verifier requires the stopped-main proof and cannot fall back to an agent-written file or live unauthenticated export.

The trusted simulator's socket bind defaults to `/var/run/docker.sock`. Set `CHI_BENCH_DOCKER_SOCKET` when the daemon uses another Unix socket path. The agent never receives this bind. The collector issues only status queries; a read-only socket bind does not itself restrict Docker API operations. This requirement applies to native Hub exports. The source Docker/Modal runner checks its own stop operation through its existing host-side transport.

Compose injects its resolved project name into the trusted simulator as `CHI_BENCH_COMPOSE_PROJECT`. The collector uses that exact project and the `main` service label to find the agent. It does not infer container identity from a hostname, which can refer to the host under host networking. A missing project identity prevents collection.

## Credentials and files

Set `HF_TOKEN` and simulator/judge provider credentials in the runner's host
environment. Compose forwards them to the simulator. The separate verifier
receives its credentials during the verifier phase. It normally receives the
collected public handbook; `HF_TOKEN` allows a handbook download if that
artifact is unavailable. Agent credentials follow the selected Harbor harness's
own configuration.

The task's `[environment.env]` contains public task and tool configuration.
Do not put simulator or judge secrets there: Harbor 0.20.0 copies those entries
into main's startup environment. The generated `[verifier.env]` is separate.
The control token is generated inside the simulator and never enters main.

A generated task archive contains:

```text
task.toml
instruction.md
README.md
environment/
  Dockerfile
  docker-compose.yaml
tests/
  Dockerfile
  test.sh
```

The archive carries no fixture, expectation, solution, or private token files.
Trusted image stages fetch the scoring materials. The agent image does not
inherit those stages. Both verifier launchers write their reward into
`/logs/verifier/reward.json`; Marathon also writes its session scorecard.

## Export and check locally

Use an empty output location:

```bash
uv run python scripts/export_harbor_tasks.py \
    --data-root data --out logs/harbor_export --org actava-ai \
    --source-revision "$SOURCE_COMMIT" \
    --dataset-revision "$DATASET_COMMIT" \
    --handbook-revision "$HANDBOOK_COMMIT"

uv run pytest tests/unit/test_export_harbor_tasks.py
```

`--data-root` accepts the downloaded dataset tree. The exporter reads
`prior_auth_um`, `prior_auth_provider`, `care_management`, and the three Marathon
session directories. A complete tree produces 75 single-domain tasks and three
Marathon tasks. Optional `tasks.jsonl` supplies viewer metadata; Marathon rows
are matched by their dataset path, independently of their session IDs.

All three revisions must be full immutable 40-character commit SHAs.
`CHI_BENCH_REF`, `CHI_BENCH_DATASET_REV`, and `CHI_BENCH_HANDBOOK_REV` carry them
through the generated builds. There is no moving `main`, tag, or unversioned
handbook fallback. The export CLI refuses dirty, nonmatching or unpublished
source checkouts. Source-runner experiments can still test local changes;
they do not establish acceptance of a published Hub package.

For a compatible newly exported Hub package:

```bash
HF_TOKEN=<approved-token> harbor run \
    -d actava-ai/chi-bench@<tag> \
    -i actava-ai/<task> \
    -a <agent> -m <model> -y
```

With the stock `claude-code` harness, use the bare native model ID. Credential
and environment flags follow Harbor's selected harness. Exporting and testing
locally do not publish or replace a Hub release. Publish a new task and dataset
version only through the organizer's release workflow.

## E2E

The exporter excludes `prior_auth_e2e`. Those tasks require the source runner's
`dual-pa-e2e` orchestrator to sequence the provider and payer phases. Run them
through the source workflow described in [the CLI reference](cli.md).
