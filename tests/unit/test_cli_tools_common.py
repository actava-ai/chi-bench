import pytest

from chi_bench.experiment.agents.cli_tools_common import _rewrite_instruction_for_mcporter


@pytest.mark.parametrize("server", ["healthverse", "chi_bench"])
@pytest.mark.parametrize(
    ("label", "role", "namespace"),
    [
        ("Patient data & provider tools", "provider", "chart"),
        ("Case data & payer tools", "payer", "payer_intake_hub"),
        ("Patient data & care-manager tools", "care-manager", "cm_chart"),
    ],
)
def test_cli_guidance_uses_discovered_tool_and_explicit_json(server, label, role, namespace):
    instruction = (
        "Clinical vignette and rules stay unchanged.\n"
        f"| {label} | `{server}` MCP server |\n"
        "| Handbook | `/workspace/skills/managed-care-operations-handbook/SKILL.md` |\n"
        f"- Use only {role} namespaces: `{namespace}`\n"
        "- Do not fabricate source evidence\n"
    )

    rewritten = _rewrite_instruction_for_mcporter(instruction)

    assert f"`{server}` MCP server" not in rewritten
    assert "npx mcporter list chi_bench --schema" in rewritten
    assert "npx mcporter call chi_bench <tool-name> --args" in rewritten
    assert "key=value" in rewritten
    assert "exact tool name" in rewritten
    assert "double-underscore" not in rewritten
    assert "<namespace>__<tool>" not in rewritten
    assert "Clinical vignette and rules stay unchanged." in rewritten
    assert (
        "| Handbook | `/workspace/skills/managed-care-operations-handbook/SKILL.md` |" in rewritten
    )
    assert f"- Use only {role} namespaces: `{namespace}`" in rewritten
    assert "- Do not fabricate source evidence" in rewritten
    assert _rewrite_instruction_for_mcporter(rewritten) == rewritten


def test_cli_rewrite_preserves_unrelated_existing_command():
    instruction = (
        "Example note contains `npx mcporter call` text.\n"
        "| Case data & payer tools | `healthverse` MCP server |\n"
        "- Use only payer namespaces: `review`\n"
    )
    rewritten = _rewrite_instruction_for_mcporter(instruction)
    assert "`healthverse` MCP server" not in rewritten
    assert rewritten.count("npx mcporter list chi_bench --schema") == 1
