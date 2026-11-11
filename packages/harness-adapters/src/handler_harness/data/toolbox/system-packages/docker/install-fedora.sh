# Docker's own packages, from Docker's repository: Fedora's moby-engine has no rootless mode.
curl -fsSL -o /etc/yum.repos.d/docker-ce.repo https://download.docker.com/linux/fedora/docker-ce.repo
dnf -y install --setopt=install_weak_deps=False \
    docker-ce docker-ce-cli docker-ce-rootless-extras docker-buildx-plugin docker-compose-plugin \
    crun passt iproute gawk nftables iptables-nft shadow-utils libcap
dnf clean all
# Rootless dockerd maps the sandbox's ids with newuidmap and newgidmap, which need their file
# capabilities: an image build does not keep them from the package.
setcap cap_setuid=ep /usr/bin/newuidmap
setcap cap_setgid=ep /usr/bin/newgidmap
# Its firewall through nftables (handler-dockerd): legacy iptables, which Docker's packages may
# bring, needs the kernel's `nat` table, which a user namespace cannot load.
# Inside a sandbox (files/): handler-dockerd starts the daemon with Handler's `runc` first on its
# PATH, crun keeping containers in the sandbox's UTS namespace (see files/runc: Docker's runc
# cannot start a container there); its state in the sandbox's own /tmp: two daemons writing one
# data root (a cache shared between sandboxes) would corrupt it. The sandbox gives what is the
# host's: /etc/subuid, /etc/subgid, /dev/fuse, /dev/net/tun (contract A.5).
install -D -m 755 files/runc /usr/local/libexec/handler-docker/runc
install -D -m 755 files/handler-dockerd /usr/local/bin/handler-dockerd
