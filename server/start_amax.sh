#!/bin/bash
#===========================================================================
# AMAX Cluster Connection Script (macOS)
# Usage: AMAX_SSH_KEY=~/.ssh/amax_key sudo -E ./start_amax.sh
#===========================================================================

set -u

REAL_USER="${SUDO_USER:-$USER}"
if [ "$(id -u)" -ne 0 ]; then
    echo "Ports 80/443 require root. Re-running with sudo..."
    exec sudo -E "$0" "$@"
fi

REAL_HOME=$(dscl . -read "/Users/$REAL_USER" NFSHomeDirectory | awk '{print $2}')
SSH_KEY_PATH="${AMAX_SSH_KEY:-$REAL_HOME/.ssh/amax_key}"
REMOTE_HOST="iipl@hduiipl.cn"
REMOTE_PORT="2123"
TARGET_IP="192.168.88.123"
SSH_OPTS="-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=60"
LOCAL_WEB_PORT=80
LOCAL_HTTPS_PORT=443

if [ ! -r "$SSH_KEY_PATH" ]; then
    echo "ERROR: SSH key is not readable: $SSH_KEY_PATH"
    echo "Set AMAX_SSH_KEY to the external key path and retry."
    exit 1
fi

MAIN_TUNNEL_PID=""
DOCKER_TUNNEL_PID=""
cleanup() {
    echo ""
    echo "Cleaning up tunnels..."
    [ -n "$MAIN_TUNNEL_PID" ] && kill "$MAIN_TUNNEL_PID" 2>/dev/null
    [ -n "$DOCKER_TUNNEL_PID" ] && kill "$DOCKER_TUNNEL_PID" 2>/dev/null
    echo "Done."
}
trap cleanup EXIT INT TERM

echo "Establishing main SSH tunnel to AMAX cluster..."
ssh -N $SSH_OPTS \
    -L ${LOCAL_WEB_PORT}:${TARGET_IP}:80 \
    -L ${LOCAL_HTTPS_PORT}:${TARGET_IP}:443 \
    -L 1080:${TARGET_IP}:1080 \
    -L 5678:${TARGET_IP}:5678 \
    -L 5680:${TARGET_IP}:5680 \
    -L 7256:${TARGET_IP}:7256 \
    -L 8000:${TARGET_IP}:8000 \
    -L 8001:${TARGET_IP}:8001 \
    -L 8765:${TARGET_IP}:8765 \
    -L 9999:${TARGET_IP}:9999 \
    -i "$SSH_KEY_PATH" \
    ${REMOTE_HOST} -p ${REMOTE_PORT} &
MAIN_TUNNEL_PID=$!

sleep 3
if ! kill -0 "$MAIN_TUNNEL_PID" 2>/dev/null; then
    echo "ERROR: SSH tunnel failed to start. Check the network and key path."
    exit 1
fi

sudo -u "$REAL_USER" open "http://127.0.0.1:${LOCAL_WEB_PORT}"

echo "##################################################"
echo "########## Welcome to AMAX system of IIPL ########"
echo "##################################################"

read -r -p "Enter docker ssh port (from web panel): " DOCKER_PORT
if ! [[ "$DOCKER_PORT" =~ ^[0-9]+$ ]] || [ "$DOCKER_PORT" -lt 1 ] || [ "$DOCKER_PORT" -gt 65535 ]; then
    echo "ERROR: Invalid docker port: $DOCKER_PORT"
    exit 1
fi

echo "Forwarding local port ${DOCKER_PORT} -> ${TARGET_IP}:${DOCKER_PORT}..."
ssh -N $SSH_OPTS -L ${DOCKER_PORT}:${TARGET_IP}:${DOCKER_PORT} -i "$SSH_KEY_PATH" ${REMOTE_HOST} -p ${REMOTE_PORT} &
DOCKER_TUNNEL_PID=$!

sleep 1
SSH_CMD="ssh root@127.0.0.1 -p ${DOCKER_PORT} -t 'cd /opt/data/private; exec /bin/bash -l'"
echo "$SSH_CMD" | sudo -u "$REAL_USER" pbcopy

echo ""
echo "Done! Web panel's SSH command now works directly:"
echo "  ssh root@127.0.0.1 -p ${DOCKER_PORT}"
echo "Private files path: /opt/data/private"

sudo -u "$REAL_USER" osascript -e "tell application \"Terminal\"" \
          -e "activate" \
          -e "do script \"${SSH_CMD}\"" \
          -e "end tell"

echo "Press Enter to close all tunnels..."
read -r
