#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
[[ $# == 2 ]] || fail 'Usage: game-mode.sh homolog|production mode-id'
select_environment "$1"
# A mode switch follows the same build/approval, recreation and rollback path.
deploy "$2"
