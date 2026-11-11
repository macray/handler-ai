docker --version
rootlesskit --version
test -x /usr/bin/dockerd-rootless.sh
getcap /usr/bin/newuidmap | grep cap_setuid
getcap /usr/bin/newgidmap | grep cap_setgid
test -x /usr/bin/crun
test -x /usr/local/libexec/handler-docker/runc
test -x /usr/local/bin/handler-dockerd
command -v nft
command -v awk
