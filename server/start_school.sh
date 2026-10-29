#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SSH_CONFIG="$CONFIG_DIR/school_ssh_config"
JUMP_HOST=hduiipl.cn
JUMP_PORT=7002
TARGET=school104

case "${1:-}" in
    100|101|102|103|104|127)
        TARGET="school$1"
        shift
        ;;
    school100|school101|school102|school103|school104|school127)
        TARGET="$1"
        shift
        ;;
    -h|--help)
        echo 'Usage: start_school.sh [100|101|102|103|104|127] [remote-command ...]'
        echo 'Default target: 104. Public DNS fallback preserves gateway host-key checks.'
        exit 0
        ;;
esac

if nc -z -G 3 -w 3 "$JUMP_HOST" "$JUMP_PORT" 2>/dev/null; then
    exec ssh -F "$SSH_CONFIG" "$TARGET" "$@"
fi

echo "School gateway is unreachable via local DNS; checking public DNS..."
CONNECT_IP=""
for resolver in https://dns.alidns.com/resolve https://dns.google/resolve; do
    answer=$(curl -fsS --connect-timeout 4 --max-time 8 "${resolver}?name=${JUMP_HOST}&type=A" 2>/dev/null) || continue
    status=$(printf '%s' "$answer" | plutil -extract Status raw -o - - 2>/dev/null) || continue
    [ "$status" = 0 ] || continue
    index=0
    while record_type=$(printf '%s' "$answer" | plutil -extract "Answer.${index}.type" raw -o - - 2>/dev/null); do
        if [ "$record_type" = 1 ]; then
            candidate=$(printf '%s' "$answer" | plutil -extract "Answer.${index}.data" raw -o - - 2>/dev/null) || break
            if [[ "$candidate" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] && nc -z -G 3 -w 3 "$candidate" "$JUMP_PORT" 2>/dev/null; then
                CONNECT_IP="$candidate"
                break 2
            fi
        fi
        index=$((index + 1))
    done
done

if [ -z "$CONNECT_IP" ]; then
    echo "ERROR: School gateway is unreachable via local and public DNS." >&2
    exit 1
fi

# Override only the jump address; the base config still pins its host key.
TEMP_CONFIG=$(mktemp "${TMPDIR:-/tmp}/school-ssh.XXXXXX")
trap 'rm -f "$TEMP_CONFIG"' EXIT
trap 'exit 130' INT
trap 'exit 129' HUP
trap 'exit 143' TERM
printf 'Host school-jump\n    HostName %s\nHost *\n    Include "%s"\n' "$CONNECT_IP" "$SSH_CONFIG" > "$TEMP_CONFIG"
echo "Using ${CONNECT_IP}:${JUMP_PORT}; verifying the saved school gateway key."
ssh -F "$TEMP_CONFIG" "$TARGET" "$@"
