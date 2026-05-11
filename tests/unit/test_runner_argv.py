import pytest
from chi_bench.experiment.runner import _forward_agent_keys


def test_forward_agent_keys_emits_present_only():
    env = {
        "ANTHROPIC_API_KEY": "ak-anthropic",
        "OPENAI_API_KEY": "ak-openai",
        # GEMINI_API_KEY absent
        "OPENROUTER_API_KEY": "ak-openrouter",
        "IRRELEVANT": "x",
    }
    flags = _forward_agent_keys(env)
    assert "--ae" in flags
    pairs = [flags[i + 1] for i, x in enumerate(flags) if x == "--ae"]
    assert "ANTHROPIC_API_KEY=ak-anthropic" in pairs
    assert "OPENAI_API_KEY=ak-openai" in pairs
    assert "OPENROUTER_API_KEY=ak-openrouter" in pairs
    assert not any(p.startswith("GEMINI_API_KEY=") for p in pairs)
    assert not any("IRRELEVANT" in p for p in pairs)


def test_forward_agent_keys_no_overrides_signature():
    """_forward_agent_keys MUST be a single-argument function — per-row override path removed."""
    import inspect
    sig = inspect.signature(_forward_agent_keys)
    assert list(sig.parameters.keys()) == ["env"], (
        f"per-row override 'overrides' param must be gone; got {list(sig.parameters)}"
    )
