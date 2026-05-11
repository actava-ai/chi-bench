"""Repackage the staged data/ tree for Hugging Face upload.

Operates in place under `data/`:
  1. Removes every task's `environment/` subdir (Dockerfile + docker-compose.yaml).
  2. Rewrites task.toml MCP URLs:  http://chi-bench-server:<port>/mcp  ->  http://localhost:<port>/mcp
                                   http://healthverse-server:<port>/mcp ->  http://localhost:<port>/mcp
                                   (catches both pre- and post-rename source trees)

After this script runs, the data/ tree is ready to:
  - upload to HF as `actava/chi-bench`
  - bake into the Docker image
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DATA_ROOT = Path("data")
URL_PATTERN = re.compile(r"http://(healthverse|chi-bench)-server:(\d+)/mcp")


def repackage_task_dir(task_dir: Path) -> tuple[bool, bool]:
    """Returns (env_removed, toml_rewritten)."""
    env_removed = False
    env_dir = task_dir / "environment"
    if env_dir.exists():
        import shutil

        shutil.rmtree(env_dir)
        env_removed = True

    toml_rewritten = False
    toml = task_dir / "task.toml"
    if toml.exists():
        text = toml.read_text()
        new_text = URL_PATTERN.sub(lambda m: f"http://localhost:{m.group(2)}/mcp", text)
        if new_text != text:
            toml.write_text(new_text)
            toml_rewritten = True

    return env_removed, toml_rewritten


def walk_tasks(root: Path):
    for task_toml in root.rglob("task.toml"):
        yield task_toml.parent


def main() -> int:
    if not DATA_ROOT.exists():
        print(f"ERROR: {DATA_ROOT}/ does not exist; run from repo root.", file=sys.stderr)
        return 1
    env_count = 0
    toml_count = 0
    for task_dir in walk_tasks(DATA_ROOT):
        env_removed, toml_rewritten = repackage_task_dir(task_dir)
        if env_removed:
            env_count += 1
        if toml_rewritten:
            toml_count += 1
    print(f"Removed environment/ from {env_count} task dirs.")
    print(f"Rewrote MCP URLs in {toml_count} task.toml files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
