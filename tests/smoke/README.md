# Smoke tests

These tests exercise integration paths that aren't covered by `tests/unit`.

## What's automated

- `test_verify_data_layout.py` — `chi-bench data verify` against synthetic data trees.
- `test_docker_image_builds.py` — `docker build --target ci-skeleton .` (skipped without docker; marked `slow` so it's gated out of the default pytest run).

To opt into the slow docker build test:

```bash
uv run pytest tests/smoke/test_docker_image_builds.py -v -m slow
```

To skip the docker build even when docker is available (e.g. fast inner loop):

```bash
CHI_BENCH_SKIP_DOCKER_BUILD=1 uv run pytest tests/smoke -v -m slow
```

## What's NOT automated (manual smoke)

A live single-task trial of one PA and one CM task requires real API keys
and ~5 minutes per trial. To run them manually:

```bash
# 1. Fill in .env
cp .env.example .env
# Populate at minimum:
#   ANTHROPIC_API_KEY=...   (required for judge — used regardless of agent model)
#   OPENAI_API_KEY=...      (for the codex agent in the example below)

# 2. Build the docker image
chi-bench docker build

# 3. Single PA-UM trial
chi-bench experiment run \
    --dataset data/prior_auth_um/tasks/pa_t008_t008_o002_p01_mdreview_payer \
    --agent codex --model openai/gpt-5.5

# 4. Single CM trial
chi-bench experiment run \
    --dataset data/care_management/tasks/cm_afib_moderate_anxious_001 \
    --agent claude-code --model anthropic/claude-opus-4-7
```

Each should produce a `result.json` under `logs/experiments/.../trial-*/`.
