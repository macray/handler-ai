"""D.9, E1: `handler account list` says an account's login in the web UI's words: "logged out on
<day>" when the login handler was given ended, "not logged in" when it has none."""

from handler_cli.account_commands import login_status


def test_a_login_that_ended_is_logged_out_one_never_given_is_not_logged_in() -> None:
    ended = {
        "status": "incomplete",
        "expiresAt": "2026-11-10T09:00:00Z",
        "problems": ["its token expired on 2026-11-10: make a new one"],
    }
    assert login_status(ended) == "logged out on 2026-11-10"
    assert login_status({"status": "incomplete", "problems": ["not logged in"]}) == "not logged in"
    assert login_status({"status": "incomplete"}) == "not logged in"
    ready = {"status": "ready", "token": "secret", "expiresAt": "2027-11-10T09:00:00Z"}
    assert login_status(ready) == "token in handler, until 2027-11-10"
