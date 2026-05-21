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
> **Running therefore requires handbook access.** Harbor resolves `${HF_TOKEN}`
> (declared in each task's `task.toml [environment.env]`) from your shell or
> `--env-file` and injects it into the container via the task's
> `environment/docker-compose.yaml`. `-y` auto-confirms the "load from env"
> prompt; `-i` selects one task (omit to run all 78):
> ```bash
> HF_TOKEN=<your-approved-hf-token> harbor run \
>     -d actava-ai/chi-bench@<tag> \
>     -i actava-ai/pa_t016_t016_o001_p01_p2p_payer \
>     -a <agent> -m <model> -y
> ```
> Note: the run flag is **not** `-e` (that is the environment *type*) and
> `--ae`/`--ek` do **not** reach the entrypoint — the `${HF_TOKEN}` template +
> compose `environment:` block is the only path that delivers it to PID1.
> Without an approved token the container exits early (code 78). The public
> dataset (`actava/chi-bench`) needs no token.

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
# 1. Export the 78 self-contained Harbor task dirs from the dataset tree
#    (75 single-domain + 3 marathon; prior_auth_e2e is intentionally excluded)
uv run python scripts/export_harbor_tasks.py \
    --data-root data --out logs/harbor_export --org actava-ai

# 2. Build the dataset manifest + publish (tasks first, then the dataset)
cd logs/harbor_export
uvx harbor auth login                       # one-time, GitHub flow
uvx harbor init "actava-ai/chi-bench" --dataset --description "…" --author "actava-ai"
uvx harbor add tasks --scan
uvx harbor publish tasks --private          # publish the 78 task packages
uvx harbor publish . -t v1.0.0 --private --no-tasks   # publish the dataset
# verify the listing, then flip to public:
#   uvx harbor dataset visibility actava-ai/chi-bench --public
```

`--data-root` can point at a local HF clone of `actava/chi-bench`; it reads the
`prior_auth_um/`, `prior_auth_provider/`, `care_management/`, and `marathon/`
families (plus the optional `tasks.jsonl` metadata sidecar). Per-task timeouts
are copied from each source `task.toml`, so marathon sessions keep their long
`agent=36000s` / `verifier=18000s` budgets.

## E2E is not exported to the hub

`prior_auth_e2e` (23 provider↔payer arena tasks) is deliberately **excluded**
from the hub export. The arena needs the two-agent `dual-pa-e2e` harness
(`chi_bench.experiment.agents.dual_pa_e2e_harness:DualPaE2EHarness`) which
sequences a provider phase → relay → payer phase in one trial — a stock
single-agent `harbor run` cannot drive it. Run E2E from this repo / the HF
dataset instead:

```bash
cb experiment run --dataset data/prior_auth_e2e/tasks/<id> \
    --agent dual-pa-e2e --provider-model <m> --payer-model <m>
# or the full arena: ./scripts/run_table.sh table2   (configs/experiments/table2_e2e_arena.yaml)
```
