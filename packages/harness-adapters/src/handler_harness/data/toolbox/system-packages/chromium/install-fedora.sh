dnf -y install --setopt=install_weak_deps=False chromium liberation-fonts dejavu-sans-fonts
dnf clean all
# by the name tools look for (Fedora's is chromium-browser). Its own sandbox cannot start under
# the `strict` confinement: tools run it with --no-sandbox (the sandbox is the boundary).
ln -s /usr/bin/chromium-browser /usr/bin/chromium
