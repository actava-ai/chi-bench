# Publishing chi-Bench to the Harbor hub

chi-Bench is listed on the [Harbor hub](https://hub.harborframework.com/datasets/actava-ai/chi-bench)
as `actava-ai/chi-bench` so Harbor users can discover and run it with
`harbor run -d actava-ai/chi-bench@<tag>`.

## How hub tasks run (fetch-at-build, no hosted image)

The hub does **not** host a chi-Bench image and chi-Bench does **not** push one
to any registry. Instead, each exported task ships a self-contained
`environment/Dockerfile` (`docker/Dockerfile.harbor`) that, at build time:

1. `git clone`s the `chi_bench` package from this public GitHub repo;
2. `hf download`s the task fixtures/worlds (`actava/chi-bench`) and the
   managed-care handbook (`actava/managed-care-operations-handbook`) from
   Hugging Face;
3. arranges them into the `/opt/chi-bench` layout the server + entrypoint
   expect.

Harbor builds this image on `harbor run` from the task archive alone. The
trial is selected by `CHI_BENCH_TASK_ID` (set in `task.toml [environment.env]`),
so the Dockerfile is **identical across all tasks**.

> **Prerequisite:** both `actava/chi-bench` and
> `actava/managed-care-operations-handbook` must be **public** on Hugging Face —
> Harbor task builds do not pass build secrets, so the `hf download` calls must
> need no token. If the handbook is gated, builders must supply `HF_TOKEN` as a
> BuildKit secret.

## What ships in a hub task (and what does not)

Each task archive contains only `task.toml`, `instruction.md`,
`environment/Dockerfile`, `tests/test.sh`, and `README.md`. It carries **no
`solution/`, no `fixtures/`, no expectations** — the scoring contract is baked
into the image at build time and the entrypoint deliberately withholds it from
the agent (no `/fixtures` symlink).

The verifier runs in the same container during Harbor's verifier phase:

- standard tasks: `python -m chi_bench.verifier.task_runtime verify --expectations-path /opt/chi-bench/tasks/$CHI_BENCH_TASK_ID/fixtures/expectations.json`
- marathon sessions: `python -m chi_bench.verifier.session_verifier --fixtures-dir … --output-dir /logs/verifier` (their `CHI_BENCH_TASK_ID` is the slash path `marathon/<domain>`).

Both write the binary reward to `/logs/verifier/reward.json`.

## Regenerating + publishing

```bash
# 1. Export 101 self-contained Harbor task dirs from the dataset tree
uv run python scripts/export_harbor_tasks.py \
    --data-root data --out logs/harbor_export --org actava-ai

# 2. Build the dataset manifest + publish (tasks first, then the dataset)
cd logs/harbor_export
uvx harbor auth login                       # one-time, GitHub flow
uvx harbor init "actava-ai/chi-bench" --dataset --description "…" --author "actava-ai"
uvx harbor add tasks --scan
uvx harbor publish tasks --private          # publish the 101 task packages
uvx harbor publish . -t v1.0.0 --private --no-tasks   # publish the dataset
# verify the listing, then flip to public:
#   uvx harbor dataset visibility actava-ai/chi-bench --public
```

`--data-root` can point at a local HF clone of `actava/chi-bench`; it expects
the `prior_auth_um/`, `prior_auth_provider/`, `care_management/`,
`prior_auth_e2e/`, and `marathon/` families plus the optional `tasks.jsonl`
metadata sidecar.
