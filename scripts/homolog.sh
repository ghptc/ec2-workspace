#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
[[ $# == 1 ]] || fail 'Usage: homolog.sh on|off|status'
case "$1" in
    on) remote docker start cod4-homolog ;;
    off) remote docker stop cod4-homolog ;;
    status) remote docker inspect --format '{{.Name}} running={{.State.Running}} status={{.State.Status}} image={{.Image}}' cod4-homolog ;;
    *) fail 'Usage: homolog.sh on|off|status' ;;
esac
