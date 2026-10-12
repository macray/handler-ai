"""Skills from a URL (D.17): a folder of a GitHub repository, or an https:// zip archive of one
skill. handlerd downloads the archive (GitHub's zip of the repository at that ref) and takes the
skill out of it with `skills.unpack`; the import itself is the archive import's.

    locate   a URL → the archive to download and the folder in it (None: a skill's own archive)
    fetch    a URL → the skill's name and files
"""

import posixpath
import re

import httpx

from . import skills

MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024  # a repository's archive; the skill in it: skills' limits
DOWNLOAD_TIMEOUT = 60.0
GITHUB = re.compile(
    r"^https://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?"
    r"(?:/(?P<kind>tree|blob)/(?P<ref>[^/]+)(?:/(?P<path>.*?))?)?/?$"
)


def locate(url: str) -> tuple[str, str | None]:
    """The archive to download, and the skill's folder in it: a GitHub repository's folder
    (`tree/<ref>/<folder>`, a `blob/<ref>/<folder>/SKILL.md`, or the repository itself: its
    default branch) is that folder of the repository's zip; any other https:// URL is a skill's
    own archive (None). A branch whose name has a `/` is not told from a folder: the first
    segment is taken as the ref."""
    if not url.startswith("https://"):
        raise skills.SkillError("a skill is fetched over https:// only")
    found = GITHUB.match(url)
    if not found:
        return url, None
    path = found["path"] or ""
    if found["kind"] == "blob":
        if posixpath.basename(path) != skills.SKILL_FILE:
            raise skills.SkillError(f"a file link of a repository must be a {skills.SKILL_FILE}")
        path = posixpath.dirname(path)
    repository = f"https://github.com/{found['owner']}/{found['repo']}"
    return f"{repository}/archive/{found['ref'] or 'HEAD'}.zip", path


def _download(url: str) -> bytes:
    data = bytearray()
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=DOWNLOAD_TIMEOUT) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes():
                data += chunk
                if len(data) > MAX_DOWNLOAD_BYTES:
                    raise skills.SkillError(f"the archive is over {MAX_DOWNLOAD_BYTES} bytes")
    except httpx.HTTPError as e:
        raise skills.SkillError(f"cannot download {url}: {e}") from None
    return bytes(data)


def fetch(url: str) -> tuple[str, dict[str, tuple[bytes, bool]]]:
    """The skill at `url`: its name and files, as `skills.unpack` gives them."""
    archive, folder = locate(url)
    return skills.unpack(_download(archive), folder)
