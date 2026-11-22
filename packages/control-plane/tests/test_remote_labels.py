"""What a paired phone is told an agent's program is (remote design): its product name, as the
web UI says it, never the code name."""

from handler_contracts import ModelAccess
from handler_control.remote import access_label, product


def test_a_program_is_named_by_its_product_name() -> None:
    """If this fails: the phone says "claude-code" where the web UI says "Claude Code"."""
    assert product("claude-code") == "Claude Code"
    assert product("gone") == "gone"  # no longer installed: its name


def test_an_agent_without_a_name_is_said_by_its_program_and_model() -> None:
    """If this fails: an unnamed Chat agent shows on the phone as `claude-code on account a`."""
    by_account = ModelAccess(harness="claude-code", account="claude-pro")
    assert access_label(by_account) == "Claude Code · account claude-pro"
    alone = ModelAccess(provider="mistral-api", model="mistral-medium")
    assert access_label(alone) == "The model alone · provider mistral-api · mistral-medium"
