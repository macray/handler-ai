"""A secret's value never on the CLI's command line (cli.a-secret-is-typed-never-an-argument):
typed at a hidden prompt, or read from stdin."""

import io

import pytest

from handler_cli import account_commands
from handler_cli.cli import parser


@pytest.mark.rule("cli.a-secret-is-typed-never-an-argument")
@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["secret", "set", "providers/x/apiKey", "sk-value"], id="secret-set"),
        pytest.param(["account", "add", "pro", "claude-code", "--token", "sk-value"], id="token"),
        pytest.param(["account", "token", "pro", "sk-value"], id="account-token"),
        pytest.param(
            ["provider", "add", "or", "--from", "openrouter", "--key", "sk-value"], id="key"
        ),
        pytest.param(["app", "secret", "notes", "apiKey", "sk-value"], id="app-secret"),
    ],
)
def test_a_command_given_a_secret_s_value_as_an_argument_is_refused(argv: list[str]) -> None:
    """If this fails: a key typed on the command line lands in the shell's history and in the
    process list any user of the computer reads."""
    without = [a for a in argv if a != "sk-value"]
    parser().parse_args(without)  # the command itself is valid
    with pytest.raises(SystemExit):
        parser().parse_args(argv)


@pytest.mark.rule("cli.a-secret-is-typed-never-an-argument")
def test_without_a_terminal_the_secret_is_read_from_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    """If this fails: a script cannot give a token without putting it on a command line."""
    monkeypatch.setattr("sys.stdin", io.StringIO("sk-ant-oat01-from-stdin\n"))
    assert account_commands.ask_token("pro") == "sk-ant-oat01-from-stdin"
