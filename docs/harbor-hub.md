# Publishing chi-Bench to the Harbor hub

chi-Bench is listed on the [Harbor hub](https://hub.harborframework.com/datasets/actava-ai/chi-bench)
as `actava-ai/chi-bench` so Harbor users can discover and run it with
`harbor run -d actava-ai/chi-bench@<tag>`.

## How hub tasks run (fetch-at-build, no hosted image)

The hub does **not** host a chi-Bench image and chi-Bench does **not** push one
to any registry. Instead, each exported task ships a self-contained
`environment/Dockerfile` (`docker/Dockerfile.harbor`):

**At build time** (Harbor builds the image on `harbor run`, secret-free):
1. `git clone`s the `chi_bench` package from this public GitHub repo;
2. `hf download`s the task fixtures/worlds from the public dataset
   (`actava/chi-bench`);
3. arranges them into the `/opt/chi-bench` layout the server expects.

**At container start** (wrapper entrypoint, `harbor-entrypoint.sh`):
4. downloads the **gated** managed-care handbook
   (`actava/managed-care-operations-handbook`) into
   `/workspace/skills/` using `HF_TOKEN` from the container env, then hands off
   to the real chi-Bench entrypoint.

The trial is selected by `CHI_BENCH_TASK_ID` (set in
`task.toml [environment.env]`), so the Dockerfile is **identical across all
tasks**.

> **Why the handbook is fetched at runtime, not build time.** Harbor's docker
> environment builds from a compose file with only `build: context` — it passes
> **no build secrets**. The handbook is `gated: manual` on HF, so a build-time
> `hf download` would 401 with no way to inject a token. Fetching it in the
> entrypoint lets Harbor forward an approved `HF_TOKEN` as a normal runtime env
> var instead.
>
> **Running therefore requires handbook access:**
> ```bash
> harbor run -d actava-ai/chi-bench@<tag> -a <agent> -m <model> \
>     -e HF_TOKEN=<your-approved-hf-token>
> ```
> Without an approved token the container exits early with a clear message.
> The public dataset (`actava/chi-bench`) needs no token.

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
