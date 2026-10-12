"""Reads a session folder's git repository for `session_files`, as a child process of handlerd:
`python -m handler_control.git_read head <folder>` prints the commit HEAD is at,
`… show <folder> <commit> <path>` the file's content at that commit; exit 1 when there is none.

The repository is the agent's: dulwich reads it and runs nothing from it (no hooks, filters,
fsmonitor, diff drivers, unlike git), and this process, not handlerd, bears what a malformed one
does (a link to a device, a huge file): memory is capped and handlerd stops waiting after a
while."""

import resource
import sys

from dulwich.object_store import tree_lookup_path
from dulwich.objects import Blob, Commit
from dulwich.repo import Repo

MEMORY = 1 << 30


def main(args: list[str]) -> int:
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY))
    try:
        with Repo(args[1]) as repo:
            if args[0] == "head":
                sys.stdout.buffer.write(repo.head())
                return 0
            commit = repo[args[2].encode()]
            assert isinstance(commit, Commit)
            _, sha = tree_lookup_path(repo.__getitem__, commit.tree, args[3].encode())
            blob = repo[sha]
            assert isinstance(blob, Blob)
            sys.stdout.buffer.write(blob.as_raw_string())
            return 0
    except Exception:  # whatever the repository holds: there is nothing to show
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
