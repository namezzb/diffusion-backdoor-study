#!/bin/bash
#===========================================================================
# AMAX Cluster Connection Script (macOS)
# Usage: ./start_amax.sh (web panel: http://127.0.0.1:8080)
# Optional: AMAX_SSH_KEY, AMAX_LOCAL_WEB_PORT, AMAX_LOCAL_HTTPS_PORT
#===========================================================================

set -u

REAL_USER="${SUDO_USER:-$USER}"
LOCAL_WEB_PORT="${AMAX_LOCAL_WEB_PORT:-8080}"
LOCAL_HTTPS_PORT="${AMAX_LOCAL_HTTPS_PORT:-8443}"
WEB_TIMEOUT="${AMAX_WEB_TIMEOUT:-30}"
for port in "$LOCAL_WEB_PORT" "$LOCAL_HTTPS_PORT"; do
    if ! [[ "$port" =~ ^[1-9][0-9]{0,4}$ ]] || [ "$port" -gt 65535 ]; then
        echo "ERROR: Invalid local port: $port"
        exit 1
    fi
done
if ! [[ "$WEB_TIMEOUT" =~ ^[1-9][0-9]{0,2}$ ]]; then
    echo "ERROR: AMAX_WEB_TIMEOUT must be between 1 and 999 seconds."
    exit 1
fi
if [ "$(id -u)" -ne 0 ] && { [ "$LOCAL_WEB_PORT" -lt 1024 ] || [ "$LOCAL_HTTPS_PORT" -lt 1024 ]; }; then
    echo "Selected ports require root. Re-running with sudo..."
    exec sudo -E "$0" "$@"
fi

REAL_HOME=$(dscl . -read "/Users/$REAL_USER" NFSHomeDirectory | awk '{print $2}')
SSH_KEY_PATH="${AMAX_SSH_KEY:-$REAL_HOME/.ssh/amax_key}"
REMOTE_HOST="iipl@hduiipl.cn"
REMOTE_PORT="2123"
TARGET_IP="192.168.88.123"
REMOTE_NAME="${REMOTE_HOST#*@}"
CONNECT_HOST="$REMOTE_NAME"
HOST_KEY_POLICY="accept-new"
WEB_URL="http://127.0.0.1:${LOCAL_WEB_PORT}"

as_user() {
    if [ "$(id -u)" -eq 0 ]; then
        sudo -u "$REAL_USER" "$@"
    else
        "$@"
    fi
}

if [ ! -r "$SSH_KEY_PATH" ]; then
    echo "ERROR: SSH key is not readable: $SSH_KEY_PATH"
    echo "Set AMAX_SSH_KEY to the external key path and retry."
    exit 1
fi

# Corporate DNS can return an unreachable address; resolve afresh, never pin a
# dynamic public IP. Keep the original hostname/port for SSH host-key checks.
if ! nc -z -G 5 -w 5 "$REMOTE_NAME" "$REMOTE_PORT" 2>/dev/null; then
    echo "Cannot reach ${REMOTE_NAME}:${REMOTE_PORT}; checking public DNS over HTTPS..."
    for resolver in https://dns.alidns.com/resolve https://dns.google/resolve; do
        answer=$(curl -fsS --connect-timeout 5 --max-time 8 "${resolver}?name=${REMOTE_NAME}&type=A" 2>/dev/null) || continue
        status=$(printf '%s' "$answer" | plutil -extract Status raw -o - - 2>/dev/null)
        [ "$status" = 0 ] || continue
        index=0
        while record_type=$(printf '%s' "$answer" | plutil -extract "Answer.${index}.type" raw -o - - 2>/dev/null); do
            if [ "$record_type" = 1 ]; then
                candidate=$(printf '%s' "$answer" | plutil -extract "Answer.${index}.data" raw -o - - 2>/dev/null)
                if [[ "$candidate" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] && nc -z -G 5 -w 5 "$candidate" "$REMOTE_PORT" 2>/dev/null; then
                    CONNECT_HOST="$candidate"
                    HOST_KEY_POLICY="yes"
                    break 2
                fi
            fi
            index=$((index + 1))
        done
    done
    if [ "$CONNECT_HOST" = "$REMOTE_NAME" ]; then
        echo "ERROR: AMAX gateway is unreachable via system and public DNS. Check the network."
        exit 1
    fi
    echo "Using public DNS address ${CONNECT_HOST}; verifying the saved key for ${REMOTE_NAME}:${REMOTE_PORT}."
fi

SSH_OPTS=(-o "HostName=$CONNECT_HOST" -o "HostKeyAlias=[$REMOTE_NAME]:$REMOTE_PORT"
    -o "UserKnownHostsFile=$REAL_HOME/.ssh/known_hosts" -o "StrictHostKeyChecking=$HOST_KEY_POLICY"
    -o BatchMode=yes -o ExitOnForwardFailure=yes -o ConnectTimeout=10 -o ConnectionAttempts=1
    -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ControlMaster=no -o ControlPath=none)

MAIN_TUNNEL_PID=""
DOCKER_TUNNEL_PID=""
cleanup() {
    echo ""
    echo "Cleaning up tunnels..."
    [ -n "$MAIN_TUNNEL_PID" ] && kill "$MAIN_TUNNEL_PID" 2>/dev/null
    [ -n "$DOCKER_TUNNEL_PID" ] && kill "$DOCKER_TUNNEL_PID" 2>/dev/null
    [ -n "$MAIN_TUNNEL_PID" ] && wait "$MAIN_TUNNEL_PID" 2>/dev/null
    [ -n "$DOCKER_TUNNEL_PID" ] && wait "$DOCKER_TUNNEL_PID" 2>/dev/null
    echo "Done."
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Establishing main SSH tunnel to AMAX cluster..."
ssh -N "${SSH_OPTS[@]}" \
    -L 127.0.0.1:${LOCAL_WEB_PORT}:${TARGET_IP}:80 \
    -L 127.0.0.1:${LOCAL_HTTPS_PORT}:${TARGET_IP}:443 \
    -L 127.0.0.1:1080:${TARGET_IP}:1080 \
    -L 127.0.0.1:5678:${TARGET_IP}:5678 \
    -L 127.0.0.1:5680:${TARGET_IP}:5680 \
    -L 127.0.0.1:7256:${TARGET_IP}:7256 \
    -L 127.0.0.1:8000:${TARGET_IP}:8000 \
    -L 127.0.0.1:8001:${TARGET_IP}:8001 \
    -L 127.0.0.1:8765:${TARGET_IP}:8765 \
    -L 127.0.0.1:9999:${TARGET_IP}:9999 \
    -i "$SSH_KEY_PATH" \
    ${REMOTE_HOST} -p ${REMOTE_PORT} &
MAIN_TUNNEL_PID=$!

deadline=$((SECONDS + WEB_TIMEOUT))
while true; do
    if ! kill -0 "$MAIN_TUNNEL_PID" 2>/dev/null; then
        echo "ERROR: SSH tunnel failed. Check the SSH error above (key, network, or occupied local port)."
        exit 1
    fi
    if curl --noproxy '*' -fsSL --max-redirs 3 --connect-timeout 1 --max-time 2 "$WEB_URL/" -o /dev/null 2>/dev/null; then
        # A failed bind must not be mistaken for an unrelated HTTP service.
        sleep 1
        kill -0 "$MAIN_TUNNEL_PID" 2>/dev/null && break
        continue
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
        echo "ERROR: Web panel did not become reachable at $WEB_URL within ${WEB_TIMEOUT}s."
        exit 1
    fi
    sleep 1
done

echo "Web panel ready: $WEB_URL"
as_user open "$WEB_URL"

echo "##################################################"
echo "########## Welcome to AMAX system of IIPL ########"
echo "##################################################"

read -r -p "Enter docker ssh port (from web panel): " DOCKER_PORT || exit 0
if ! [[ "$DOCKER_PORT" =~ ^[1-9][0-9]{0,4}$ ]] || [ "$DOCKER_PORT" -gt 65535 ]; then
    echo "ERROR: Invalid docker port: $DOCKER_PORT"
    exit 1
fi

echo "Forwarding local port ${DOCKER_PORT} -> ${TARGET_IP}:${DOCKER_PORT}..."
ssh -N "${SSH_OPTS[@]}" -L 127.0.0.1:${DOCKER_PORT}:${TARGET_IP}:${DOCKER_PORT} -i "$SSH_KEY_PATH" ${REMOTE_HOST} -p ${REMOTE_PORT} &
DOCKER_TUNNEL_PID=$!

sleep 1
if ! kill -0 "$DOCKER_TUNNEL_PID" 2>/dev/null; then
    echo "ERROR: Docker SSH tunnel failed to start."
    exit 1
fi
SSH_CMD="ssh root@127.0.0.1 -p ${DOCKER_PORT} -t 'cd /opt/data/private; exec /bin/bash -l'"
echo "$SSH_CMD" | as_user pbcopy

echo ""
echo "Done! Web panel's SSH command now works directly:"
echo "  ssh root@127.0.0.1 -p ${DOCKER_PORT}"
echo "Private files path: /opt/data/private"

as_user osascript -e "tell application \"Terminal\"" \
          -e "activate" \
          -e "do script \"${SSH_CMD}\"" \
          -e "end tell"

echo "Press Enter to close all tunnels..."
read -r
