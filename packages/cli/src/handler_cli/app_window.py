"""Opening a mini app in its own window (docs/dev/design/miniapps.md §5.1).

Firefox first (a dedicated profile, `handler-apps`: apps' cookies and storage stay out of normal
browsing, and its toolbars are hidden, since Firefox has no `--app` mode), then Chromium's app
mode, then the default browser. `HANDLER_APP_BROWSER` (firefox · chromium · default) forces one.
"""

import os
import shutil
import subprocess
import webbrowser
from pathlib import Path

# the window's app id: GNOME groups app windows apart from the browser
WINDOW_CLASS = "handler-apps"

USER_JS = """\
// handler: the profile mini apps open in (handler app open). Rewritten by handler.
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.page", 0);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.tabs.warnOnClose", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
"""

USER_CHROME = """\
/* handler: an app window, not a browser window. Rewritten by handler. */
#TabsToolbar, #nav-bar, #PersonalToolbar, #titlebar { visibility: collapse !important; }
"""

CHROMIUMS = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")


def profiles_dir() -> Path:
    xdg = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return Path(os.environ.get("HANDLER_DATA_DIR", xdg / "handler-ai"))


def firefox_profile(root: Path) -> Path:
    """The `handler-apps` Firefox profile, created or refreshed (only handler's two files)."""
    profile = root / "firefox-apps"
    (profile / "chrome").mkdir(parents=True, exist_ok=True)
    (profile / "user.js").write_text(USER_JS)
    (profile / "chrome" / "userChrome.css").write_text(USER_CHROME)
    return profile


def argv(url: str, browser: str, root: Path) -> list[str] | None:
    """The command opening `url` in an app window; None: the default browser."""
    if browser == "firefox" and (firefox := shutil.which("firefox")):
        profile = firefox_profile(root)
        return [firefox, "--profile", str(profile), "--name", WINDOW_CLASS, "--new-window", url]
    if browser == "chromium" and (
        chromium := next(filter(None, map(shutil.which, CHROMIUMS)), None)
    ):
        data = root / "chromium-apps"
        return [chromium, f"--user-data-dir={data}", f"--class={WINDOW_CLASS}", f"--app={url}"]
    return None


def choose() -> str:
    forced = os.environ.get("HANDLER_APP_BROWSER")
    if forced:
        return forced
    if shutil.which("firefox"):
        return "firefox"
    return "chromium" if any(shutil.which(c) for c in CHROMIUMS) else "default"


def open_window(url: str) -> None:
    command = argv(url, choose(), profiles_dir())
    if command is None:
        webbrowser.open(url)
        return
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # outlives `handler` (a keyboard shortcut runs it and returns)
    )
