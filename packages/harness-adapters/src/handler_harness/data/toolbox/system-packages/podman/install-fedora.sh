dnf -y install --setopt=install_weak_deps=False podman fuse-overlayfs passt libcap util-linux-core
dnf clean all
# Rootless podman maps the sandbox's ids with newuidmap and newgidmap, which need their file
# capabilities: an image build does not keep them from the package.
setcap cap_setuid=ep /usr/bin/newuidmap
setcap cap_setgid=ep /usr/bin/newgidmap
# Its configuration inside a sandbox (files/): storage on fuse-overlayfs (the kernel overlay
# cannot stack on the sandbox's own overlay); no systemd nor journald (cgroupfs, events and
# `podman logs` in files); no sysctls and the sandbox's UTS namespace (the sandbox's seccomp
# profile refuses sethostname), none of which the sandbox can delegate. Its container database,
# volumes and networks are the sandbox's own, in /tmp: the image store
# (~/.local/share/containers/storage) may be a cache shared with other sandboxes, whose sweeps
# would remove networks they see there, and a database there would be another sandbox's
# (podman refuses one made with another runroot) and, after a restart, would hold containers
# whose runtime state is gone. The sandbox gives what is the host's: /etc/subuid, /etc/subgid,
# /dev/fuse, /dev/net/tun (contract A.5).
install -m 644 files/storage.conf files/containers.conf /etc/containers/
# `podman` as an agent runs it: its sandbox's state kept in the image store, and what ended
# sandboxes left there freed (its header says how)
install -m 755 files/podman /usr/local/bin/podman
