# Handler's base of a Fedora toolbox (contract B.7): what Handler and the harness recipes rely on,
# and the command-line tools any agent uses. Fedora: official images for x86_64 and arm64 (Apple
# silicon runs it natively). `latest` is the current release: an update may move to the next one.
FROM docker.io/library/fedora:latest

RUN dnf -y upgrade \
    && dnf -y install --setopt=install_weak_deps=False \
        git openssh-clients ca-certificates curl wget unzip zip tar \
        ripgrep fd-find jq less which diffutils findutils procps-ng file patch \
        python3 python3-pip python-unversioned-command uv \
        nodejs npm \
    && dnf clean all

# ~/.local/bin: what uv, pip and pipx install for the user (the `~/.local` cache). Bun is the
# app-builder tool's, for the agents that write apps.
ENV LANG=C.UTF-8 \
    HOME=/home/agent \
    PATH=/home/agent/.local/bin:/usr/local/bin:/usr/bin:/usr/sbin
