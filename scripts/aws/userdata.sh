#!/bin/bash
# User-data for one bare-metal A6 ladder session. drive-metal.sh `wait` goes on only
# if SHUTDOWN_ARMED exists, the per-boot re-arm below is installed, and
# /run/systemd/shutdown/scheduled says poweroff 61-91 minutes ahead; otherwise it
# terminates the instance. --instance-initiated-shutdown-behavior terminate turns
# the poweroff into a termination, which bounds the bill if the operator is gone.
#
# SURVIVES A REBOOT. A pending shutdown lives in /run, which a reboot empties, and
# user-data runs once per instance -- this AMI boots with panic=-1, so a host panic
# would reboot into an unbounded instance. So the deadline is written to disk as an
# absolute time, and a per-boot script re-arms the remainder, or powers off at once
# if the deadline has passed. What it cannot bound is a kernel that hangs without
# rebooting; README.md says so.
#
# The +90 here and SHUTDOWN_MIN_EXPECTED in drive-metal.sh must agree
# (tests/test_aws_tooling.py checks it).
M=/var/lib/cloud/instance
MIN=90
shutdown -h +$MIN "auto-terminate: A6 ladder session budget" && touch "$M/SHUTDOWN_ARMED"
echo $(( $(date +%s) + MIN * 60 )) > /var/lib/qnx-metal-deadline
mkdir -p /var/lib/cloud/scripts/per-boot
cat > /var/lib/cloud/scripts/per-boot/qnx-metal-deadline.sh <<'EOS'
#!/bin/sh
d="$(cat /var/lib/qnx-metal-deadline 2>/dev/null)" || exit 0
left=$(( (d - $(date +%s)) / 60 ))
if [ "$left" -le 0 ]; then shutdown -h now "auto-terminate: session deadline passed"
else shutdown -h +"$left" "auto-terminate: session deadline, re-armed after a reboot"; fi
EOS
chmod 755 /var/lib/cloud/scripts/per-boot/qnx-metal-deadline.sh

# Everything the run needs, installed before the operator logs in. A failure is
# written down, never papered over with a readiness file.
set -e
trap 'touch "$M/PROVISION_FAILED"' ERR
export DEBIAN_FRONTEND=noninteractive
apt-get -o DPkg::Lock::Timeout=300 update -y
apt-get -o DPkg::Lock::Timeout=300 install -y --no-install-recommends \
  qemu-system-arm qemu-utils bridge-utils iproute2 \
  build-essential python3 net-tools gawk
usermod -aG kvm ubuntu
touch "$M/PROVISIONED"
