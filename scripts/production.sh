#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
[[ $# == 1 ]] || fail 'Usage: production.sh on|off|status'
case "$1" in on|off|status) ;; *) fail 'Usage: production.sh on|off|status' ;; esac
select_environment production
need flock
mkdir -p -- "$ROOT/.state"
exec 9> "$ROOT/.state/deploy.lock"
flock -n 9 || fail 'Another operation is running in this checkout'
case "$1" in
    on|off)
        running=$(remote docker inspect --format '{{.State.Running}}' "$container")
        [[ "$running" == true || "$running" == false ]] || fail 'Cannot determine production state'
        if [[ "$1" == on && "$running" == false ]]; then
            remote docker start "$container"
        elif [[ "$1" == off && "$running" == true ]]; then
            confirm 'Stopping cod4-production disconnects players.'
            remote docker stop "$container"
        fi ;;
    status) remote docker inspect --format '{{.Name}} running={{.State.Running}} status={{.State.Status}} image={{.Image}} configured_image={{.Config.Image}}' "$container" ;;
esac
