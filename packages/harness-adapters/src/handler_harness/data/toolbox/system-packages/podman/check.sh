podman --version
getcap /usr/bin/newuidmap | grep cap_setuid
getcap /usr/bin/newgidmap | grep cap_setgid
test -x /usr/bin/fuse-overlayfs
grep -q fuse-overlayfs /etc/containers/storage.conf
grep -q cgroupfs /etc/containers/containers.conf
