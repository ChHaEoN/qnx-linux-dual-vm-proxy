#!/bin/bash
# aw-entrypoint.sh -- the project entrypoint of every container started from the Autoware image or built on it
# (sdv/aw; Phase 8 WP4b 7.1, local branch only, decision 15).
#
# It replaces the image's own /docker-entrypoint.sh, which turns the host's loopback multicast flag on and raises three
# kernel network settings whenever the container is allowed to, with only a warning when it is not (the Phase 8
# specification's 2.12; the project's local design notes, not in this tree). That script never runs here:
#
#   docker run --entrypoint /sdv-aw/aw-entrypoint.sh --user aw --cap-drop ALL --security-opt no-new-privileges \
#       -v <tree>/sdv/aw:/sdv-aw:ro ... IMAGE@sha256:<digest> COMMAND [ARGS...]
#
# It refuses to run as root or when `id -u` prints no number (exit 2: the container was started without --user aw), and
# with no command (exit 2); it sources ROS 2 Jazzy's setup file and then Autoware's (exit 1 if either cannot be
# sourced), and replaces itself with the command, whose exit status is the container's. It changes nothing outside
# the container: no network or kernel setting, no account, no file's owner or mode, and it writes no file.
case "$(id -u)" in
	'' | 0 | *[!0-9]*)
		echo "aw-entrypoint.sh: refused: running as root, or id -u printed no number; start the container with --user aw" >&2
		exit 2
		;;
esac
if [ "$#" -eq 0 ]; then
	echo "aw-entrypoint.sh: refused: no command given" >&2
	exit 2
fi
source /opt/ros/jazzy/setup.bash || exit 1
source /opt/autoware/setup.bash || exit 1
exec "$@"
