#!/usr/bin/env bash
# Backward-compatibility wrapper: delegates to deploy/deploy-frontend.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/../deploy/deploy-frontend.sh" "$@"
