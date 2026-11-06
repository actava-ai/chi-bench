"""Every GitHub-hosted job names an explicit runner image, never a floating label.

`ubuntu-latest` (and `windows-latest` / `macos-latest`) is an alias GitHub moves
to a new OS image on its own schedule. When it moved to ubuntu-26.04 the
regression E2E sweep broke 8/8 with no change on our side. A pinned label such
as `ubuntu-24.04` only changes when someone edits it in a reviewed PR.

Stdlib only (no YAML parser): `runs-on` values are read line by line, which
covers the scalar, flow-list and block-list forms. A label that reaches
`runs-on` some other way (a `${{ matrix.os }}` value, a `labels:` mapping) is
caught by a backstop: any `ubuntu-latest` / `macos-latest` / `windows-latest`
token outside a comment fails too. Self-hosted and custom labels are left alone.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / "workflows"

_RUNS_ON = re.compile(r"^(?P<indent>\s*)runs-on:\s*(?P<value>.*)$")
_ITEM = re.compile(r"^(?P<indent>\s*)-\s*(?P<value>.+)$")
_HOSTED_LATEST = re.compile(r"\b(?:ubuntu|macos|windows)-latest\b")


def _clean(value: str) -> str:
    value = value.split(" #", 1)[0].strip()
    return value.strip("'\"")


def runs_on_labels(text: str) -> list[tuple[int, str]]:
    """Return (line number, label) for every runs-on label in a workflow."""
    labels: list[tuple[int, str]] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = _RUNS_ON.match(line)
        if not match:
            continue
        value = _clean(match.group("value"))
        if value.startswith("["):
            labels += [
                (i + 1, _clean(v)) for v in value.strip("[]").split(",") if v.strip()
            ]
        elif value:
            labels.append((i + 1, value))
        else:
            indent = len(match.group("indent"))
            for j in range(i + 1, len(lines)):
                item = _ITEM.match(lines[j])
                if not item or len(item.group("indent")) <= indent:
                    break
                labels.append((j + 1, _clean(item.group("value"))))
    return labels


def _uncommented(line: str) -> str:
    return "" if line.lstrip().startswith("#") else line.split(" #", 1)[0]


def floating_labels(text: str) -> list[tuple[int, str]]:
    """(line, label) for every floating runner label, one entry per line."""
    found = {n: label for n, label in runs_on_labels(text) if label.endswith("-latest")}
    for i, line in enumerate(text.splitlines()):
        token = _HOSTED_LATEST.search(_uncommented(line))
        if token and i + 1 not in found:
            found[i + 1] = token.group(0)
    return sorted(found.items())


class FloatingLabelDetectorTest(unittest.TestCase):
    """Positive control: the detector catches the old content and accepts the fix."""

    def test_flags_floating_labels_in_every_form(self) -> None:
        old = (
            "jobs:\n"
            "  a:\n"
            "    runs-on: ubuntu-latest\n"
            "  b:\n"
            "    runs-on: 'macos-latest'  # comment\n"
            "  c:\n"
            "    runs-on: [self-hosted, windows-latest]\n"
            "  d:\n"
            "    runs-on:\n"
            "      - ubuntu-latest\n"
        )
        self.assertEqual(
            floating_labels(old),
            [
                (3, "ubuntu-latest"),
                (5, "macos-latest"),
                (7, "windows-latest"),
                (10, "ubuntu-latest"),
            ],
        )

    def test_flags_floating_labels_reaching_runs_on_indirectly(self) -> None:
        old = (
            "jobs:\n"
            "  a:\n"
            "    strategy:\n"
            "      matrix:\n"
            "        os: [ubuntu-24.04, ubuntu-latest]\n"
            "    runs-on: ${{ matrix.os }}\n"
            "  b:\n"
            "    runs-on:\n"
            "      group: hosted\n"
            "      labels: windows-latest\n"
        )
        self.assertEqual(
            floating_labels(old), [(5, "ubuntu-latest"), (10, "windows-latest")]
        )

    def test_ignores_floating_labels_in_comments(self) -> None:
        commented = (
            "jobs:\n"
            "  # was ubuntu-latest until the 26.04 move\n"
            "  a:\n"
            "    runs-on: ubuntu-24.04  # not ubuntu-latest\n"
            "    steps:\n"
            "      - uses: tonistiigi/binfmt:latest\n"
        )
        self.assertEqual(floating_labels(commented), [])

    def test_accepts_pinned_and_custom_labels(self) -> None:
        pinned = (
            "jobs:\n"
            "  a:\n"
            "    runs-on: ubuntu-24.04\n"
            "  b:\n"
            "    runs-on: ubuntu-24.04-arm\n"
            "  c:\n"
            "    runs-on: [self-hosted, linux, ubuntu-arm64]\n"
            "  d:\n"
            "    runs-on:\n"
            "      - self-hosted\n"
            "    steps:\n"
            "      - run: echo latest\n"
        )
        self.assertEqual(floating_labels(pinned), [])
        self.assertEqual(
            [label for _, label in runs_on_labels(pinned)],
            [
                "ubuntu-24.04",
                "ubuntu-24.04-arm",
                "self-hosted",
                "linux",
                "ubuntu-arm64",
                "self-hosted",
            ],
        )


class WorkflowRunnerPinsTest(unittest.TestCase):
    def test_workflows_exist(self) -> None:
        self.assertTrue(
            list(WORKFLOWS.glob("*.y*ml")), f"no workflows under {WORKFLOWS}"
        )

    def test_no_job_uses_a_floating_runner_label(self) -> None:
        problems = [
            f"{path.name}:{line}: {label} (pin an explicit image, e.g. ubuntu-24.04)"
            for path in sorted(WORKFLOWS.glob("*.y*ml"))
            for line, label in floating_labels(path.read_text())
        ]
        self.assertEqual(problems, [], "\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
