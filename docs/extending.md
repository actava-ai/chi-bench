# Extending chi-bench

To climb the leaderboard you swap in a better **model**, a better **agent harness**, or both — then run the standard `cb submission {validate,run,status,prepare}` flow. The packet at `logs/submissions/<id>/packet/...` is what you upload; you don't need to PR chi-bench.

| You want to… | Read | Code? |
|---|---|---|
| Use a different model on an existing harness | [§ 1](#-1-new-model) | No |
| Plug in your own agent loop | [§ 2](#-2-new-agent-harness) | Yes (~50–500 lines) |
| Both | [§ 3](#-3-both) | Yes |
| See what's registered | `cb agent list` | — |

---

## § 1 — New model

Three concrete cases. Pick the one that matches your provider.

### Case A: your model lives on an OpenAI-compatible endpoint

vLLM, Together, your own server — anything that speaks the OpenAI chat-completions API.

**`.env`:**

```bash
OPENAI_BASE_URL=https://vllm.my-org.com/v1
OPENAI_API_KEY=sk-vllm-...
ANTHROPIC_API_KEY=sk-ant-...          # required: the judge runs claude-opus-4-7
```

**`configs/submissions/my-finetune.yaml`:**

```yaml
schema: chi-bench/submission/v1
submission:
  id: my-team-my-finetune
  team: My Team
  contact: you@example.com
  agent: openai-agents
  model: my-org/my-finetune
run:
  environment: modal
  env_file: .env
dataset:
  version: chi-bench-v1.0.0
  domains: [pa_provider, pa_um, cm]
```

Run `uv run cb submission validate -f configs/submissions/my-finetune.yaml` and continue.

### Case B: your model is on OpenRouter (or any `vendor/id`-style provider)

Drop the `OPENAI_BASE_URL` line. `openai-agents` auto-routes any `<vendor>/<id>` model id through OpenRouter using `OPENROUTER_API_KEY`.

```bash
OPENROUTER_API_KEY=sk-or-...
ANTHROPIC_API_KEY=sk-ant-...
```

```yaml
submission:
  agent: openai-agents
  model: anthropic/claude-opus-4-7    # or xai/grok-4.3, deepseek/deepseek-v4, etc.
```

### Case C: your model is on an Anthropic-compatible proxy

Bedrock-fronted, internal gateway, anything that speaks the Anthropic API.

```bash
ANTHROPIC_BASE_URL=https://anthropic.my-proxy.com
ANTHROPIC_API_KEY=sk-ant-proxy-...
```

```yaml
submission:
  agent: claude-code
  model: anthropic/<your-id>
```

> **The judge is not affected.** chi-bench strips `ANTHROPIC_BASE_URL` from the judge's subprocess env so `claude-opus-4-7` always hits `api.anthropic.com` (`src/chi_bench/verifier/judge/claude_runner.py:_subprocess_env`). The pin is unconditional — routing the judge would break leaderboard comparability. Your `ANTHROPIC_API_KEY` is forwarded as-is, so real Anthropic uses it for grading.

### Which harness supports which provider?

| Harness | OpenAI-direct | OpenRouter | Custom `OPENAI_BASE_URL` | Anthropic / proxy |
|---|:---:|:---:|:---:|:---:|
| `openai-agents` | ✅ | ✅ | ✅ | via OpenRouter |
| `deepagents` | ✅ | ✅ | ✅ | ✅ |
| `claude-code` | — | — | — | ✅ |
| `codex-cli` | ✅ | ✅ | ✅ | — |
| `hermes`, `openclaw` | ✅ | ✅ | ✅ | ✅ |
| `gemini-cli` | — | — | — | — (Gemini only) |

If no harness covers your provider — write one (§ 2).

---

## § 2 — New agent harness

A chi-bench harness is a Python class that runs **inside** the chi-bench Docker image, drives your agent loop, and writes logs to `/logs/agent/`. The reference implementation is `openai-agents` (`src/chi_bench/experiment/agents/openai_agents_harness.py`).

### Step 1: copy the starting point that matches your shape

| Your agent is… | Copy from | Lines |
|---|---|---|
| A Python SDK loop (most common) | `openai_agents_harness.py` + `openai_agents_runner.py` | ~50 (harness) + your loop |
| A CLI you shell out to (e.g. `your-agent run …`) | `claude_code_cli_harness.py` | ~80 total |
| Built on LangGraph / similar framework | `deepagents_harness.py` | reference for env mapping |

### Step 2: minimal harness skeleton

Save as `src/chi_bench/experiment/agents/my_agent_harness.py`. This is the complete file:

```python
"""My custom chi-bench harness."""

from __future__ import annotations

import os
import shlex
from typing import TYPE_CHECKING

from harbor.agents.installed.base import BaseInstalledAgent, with_prompt_template

if TYPE_CHECKING:
    from harbor.environments.base import BaseEnvironment
    from harbor.models.agent.context import AgentContext


class MyAgentHarness(BaseInstalledAgent):
    SUPPORTS_ATIF: bool = False   # set True once you emit ATIF (see § 2.5)

    @staticmethod
    def name() -> str:
        return "my-agent"          # this is what goes in submission.agent

    def get_version_command(self) -> str | None:
        return "uv pip show --python /workspace/.venv my-agent | grep ^Version: | cut -d' ' -f2"

    async def install(self, environment: BaseEnvironment) -> None:
        """Runs once per trial container, as root."""
        await self.exec_as_root(
            environment,
            command="uv pip install --no-cache-dir --python /workspace/.venv my-agent==1.0",
        )

    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        """Runs once per trial. Drive the agent here."""
        mcp_url = next((s.url for s in self.mcp_servers if s.url), "")
        if not mcp_url:
            raise RuntimeError("no MCP server URL — check task.toml")

        await self.exec_as_agent(
            environment,
            command=(
                f"echo {shlex.quote(instruction)} > /tmp/instruction.md && "
                "python -m chi_bench.experiment.agents.my_agent_runner "
                f"--instruction-file /tmp/instruction.md "
                f"--mcp-url {shlex.quote(mcp_url)} "
                "2>&1 | tee /logs/agent/run_log.txt"
            ),
            env={
                "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
                "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL", ""),
                "MY_AGENT_MODEL": self.model_name or "gpt-4",
            },
        )
```

That's enough for chi-bench to dispatch your agent. Your actual agent loop goes in `my_agent_runner.py` (next step).

### Step 3: write the runner

The runner is the module invoked above as `python -m chi_bench.experiment.agents.my_agent_runner`. It reads the instruction, connects to MCP, and runs your agent. Minimal skeleton:

```python
"""My agent runner — executed inside the trial container."""

import argparse
import asyncio
import os

from openai import AsyncOpenAI    # or whatever SDK you use


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instruction-file", required=True)
    parser.add_argument("--mcp-url", required=True)
    args = parser.parse_args()

    with open(args.instruction_file) as f:
        instruction = f.read()

    client = AsyncOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
    )

    # Your agent loop: connect to MCP at args.mcp_url, drive turns, etc.
    # See openai_agents_runner.py for a complete reference.
    ...


if __name__ == "__main__":
    asyncio.run(main())
```

For a working end-to-end example see `openai_agents_runner.py` (687 lines).

### Step 4: register, rebuild, smoke-test

```bash
# 1. Register in src/chi_bench/experiment/agents/registry.py — add one line:
#    "my-agent": "chi_bench.experiment.agents.my_agent_harness:MyAgentHarness",

# 2. (Skip if your harness only uses keys already on the list.)
#    If you need new provider env vars, append them to AGENT_ENV_ALLOWLIST
#    in src/chi_bench/experiment/runner.py:37.

# 3. Confirm registration.
uv run cb agent list                          # your agent should appear as kind=in-tree

# 4. Rebuild the image so your new files are baked in.
uv run cb docker build

# 5. Smoke-test against one task before the full submission run.
uv run cb experiment run \
    --dataset data/prior_auth_provider/tasks/<one-task-dir> \
    --agent my-agent \
    --model <your-model-id>
```

If the smoke test passes, run the standard submission flow — `submission.agent: my-agent` is all that's different.

### Step 5: common mistakes (read before debugging)

These are the failure modes that have bitten every harness so far. The line numbers point to `openai_agents_harness.py`.

- **Forgot the venv prefix in `install()`.** Use `uv pip install --python /workspace/.venv …`. Without it, the package lands in the wrong site-packages and your runner errors with `ModuleNotFoundError` at trial start.
- **Forgot to `tee` the runner's stdout.** Without `2>&1 | tee /logs/agent/run_log.txt`, a failure mid-trial leaves you with no log to read. Modal makes this especially painful.
- **Forgot `shlex.quote(instruction)`.** Task instructions sometimes contain `$`, backticks, or quotes. Without quoting, the shell mangles them and your agent runs on a corrupted prompt.
- **Per-row API keys aren't picked up.** Harbor's `--ae` flag populates `self._extra_env`, not `os.environ`. If your routing reads `os.environ` directly, mirror the keys at `run()` entry. See `openai_agents_harness.py:191-194`.
- **`_extra_env` clobbers your routing decisions.** Harbor merges `_extra_env` over the env you pass to `exec_as_agent`. If you set `OPENAI_BASE_URL` and the shared `.env` also has one, theirs wins. Strip the conflicting keys from `self._extra_env` before exec, restore in `finally`. See `openai_agents_harness.py:204-233`.

### Step 6 (optional): emit an ATIF trajectory

If you want cost rollups and per-step trace analysis on the leaderboard side, translate your runner's logs to **ATIF v1.2** in `populate_context_post_run`. Without ATIF, your trial still scores correctly — the verifier reads the workspace, not the trajectory.

Reference implementation: `openai_agents_harness.py:240-465` (`populate_context_post_run` + `_build_atif_trajectory`). Harbor types live at `harbor.models.trajectories.*`.

---

## § 3 — Both

Build the harness against a known-public model first (§ 2 with `model: openai/gpt-4` or similar), smoke-test it on one task, *then* swap in your custom endpoint (§ 1). Debugging two unknowns at once takes 4× longer than doing them in sequence.

---

## § 4 — Submitting (nothing changes)

The flow is the same as for a built-in agent. `submission.agent: my-agent` and the standard 5 commands:

```bash
uv run cb submission validate -f configs/submissions/<your-id>.yaml
uv run cb submission run      -f configs/submissions/<your-id>.yaml
uv run cb submission status   -f configs/submissions/<your-id>.yaml
uv run cb submission prepare  -f configs/submissions/<your-id>.yaml
```

`cb submission validate` emits a soft warning for unknown agent names (it can't tell whether the name is intentional or a typo). It does not block submission.

---

## § 5 — Contributing upstream (optional)

If you want others to reproduce your submission, open a PR with your harness file(s), the registry line, and a row in the § 1 compatibility matrix. The parametrized test `test_import_paths_resolve_to_base_installed_agent` in `tests/unit/test_agent_registry.py` will pick up your entry automatically. **Not a leaderboard requirement.**

---

## § 6 — Reference

### Harness contract (Harbor `BaseInstalledAgent`)

| Member | Required? | Purpose |
|---|---|---|
| `name() -> str` | yes | Agent name used in `submission.agent` |
| `install(environment)` | yes | Set up the container; runs as root once per trial |
| `run(instruction, environment, context)` | yes | Execute the agent loop |
| `populate_context_post_run(context)` | no | Read metrics + emit ATIF trajectory |
| `get_version_command() -> str \| None` | no | Shell command that prints your package version |
| `CLI_FLAGS: list[CliFlag]` | no | Tunable knobs (e.g. `max_turns`) |
| `SUPPORTS_ATIF: bool` | no | True if you emit ATIF v1.2 trajectories |

`BaseInstalledAgent` is owned by Harbor; consult Harbor's docs for the upstream contract.

### Useful paths

- **Registry:** `src/chi_bench/experiment/agents/registry.py`
- **Env allowlist:** `AGENT_ENV_ALLOWLIST` in `src/chi_bench/experiment/runner.py:37`
- **Reference harness:** `src/chi_bench/experiment/agents/openai_agents_harness.py`
- **Reference runner:** `src/chi_bench/experiment/agents/openai_agents_runner.py`
- **CLI reference:** [`docs/cli.md`](cli.md)

### Known limitations

- The submission YAML doesn't expose per-trial harness kwargs (`ExperimentConfig.agent_kwargs` in `src/chi_bench/experiment/config.py`). If your harness needs a runtime knob, see `dual_pa_e2e_harness.py` for the precedent.
