#!/bin/sh
set -eu
printf "#!/bin/sh\necho fake-cc\n" > /usr/local/bin/fake-cc
chmod +x /usr/local/bin/fake-cc
