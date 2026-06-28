#!/bin/bash
#===========================================================================
# AMAX Cluster Connection Script (macOS)
# Usage: sudo ./start_amax.sh
#===========================================================================

# --- Require root for binding port 80/443 ---
REAL_USER="${SUDO_USER:-$USER}"
if [ "$(id -u)" -ne 0 ]; then
    echo "Ports 80/443 require root. Re-running with sudo..."
    exec sudo "$0" "$@"
fi

# --- Configuration ---
SSH_KEY_PATH="/tmp/temp_ssh_key_$$"
REMOTE_HOST="iipl@hduiipl.cn"
REMOTE_PORT="2123"
TARGET_IP="192.168.88.123"
SSH_OPTS="-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=60"
LOCAL_WEB_PORT=80
LOCAL_HTTPS_PORT=443

# --- Write SSH private key ---
cat > "$SSH_KEY_PATH" << 'SSHKEY_EOF'
-----BEGIN OPENSSH PRIVATE KEY-----
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
JbDjeUIwzmhbMAAAALMjgzODhAU3RyaXg=
-----END OPENSSH PRIVATE KEY-----
SSHKEY_EOF

chmod 600 "$SSH_KEY_PATH"

# --- Cleanup on exit ---
MAIN_TUNNEL_PID=""
DOCKER_TUNNEL_PID=""
cleanup() {
    echo ""
    echo "Cleaning up tunnels and temp key..."
    [ -n "$MAIN_TUNNEL_PID" ] && kill "$MAIN_TUNNEL_PID" 2>/dev/null
    [ -n "$DOCKER_TUNNEL_PID" ] && kill "$DOCKER_TUNNEL_PID" 2>/dev/null
    rm -f "$SSH_KEY_PATH"
    echo "Done."
}
trap cleanup EXIT INT TERM

# --- Start main SSH tunnel ---
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
    echo "ERROR: SSH tunnel failed to start. Check your network connection."
    exit 1
fi

# --- Open browser (as the real user, not root) ---
sudo -u "$REAL_USER" open "http://127.0.0.1:${LOCAL_WEB_PORT}"

echo "##################################################"
echo "########## Welcome to AMAX system of IIPL ########"
echo "##################################################"

# --- Ask for Docker SSH port ---
read -p "Enter docker ssh port (from web panel): " DOCKER_PORT
if [ -z "$DOCKER_PORT" ]; then
    echo "ERROR: No port entered. Exiting..."
    exit 1
fi

# --- Start Docker SSH tunnel (same local port as remote) ---
echo "Forwarding local port ${DOCKER_PORT} -> ${TARGET_IP}:${DOCKER_PORT}..."
ssh -N $SSH_OPTS -L ${DOCKER_PORT}:${TARGET_IP}:${DOCKER_PORT} -i "$SSH_KEY_PATH" ${REMOTE_HOST} -p ${REMOTE_PORT} &
DOCKER_TUNNEL_PID=$!

sleep 1

# --- Copy SSH command to clipboard ---
SSH_CMD="ssh root@127.0.0.1 -p ${DOCKER_PORT} -t 'cd /opt/data/private; exec /bin/bash -l'"
echo "$SSH_CMD" | sudo -u "$REAL_USER" pbcopy

echo ""
echo "Done! Web panel's SSH command now works directly:"
echo ""
echo "  ssh root@127.0.0.1 -p ${DOCKER_PORT}"
echo ""
echo "(Already copied to clipboard)"
echo "Private files path: /opt/data/private"
echo ""

# --- Open SSH in new Terminal window (as real user) ---
sudo -u "$REAL_USER" osascript -e "tell application \"Terminal\"" \
          -e "activate" \
          -e "do script \"${SSH_CMD}\"" \
          -e "end tell"

echo "Press Enter to close all tunnels and clean up..."
read
