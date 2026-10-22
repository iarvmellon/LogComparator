#!/bin/sh
# Run on the Docker host. Reserve one logical CPU's worth of time for Tango.
set -eu
cd -- "$(dirname -- "$0")"
logical_cpus=$(docker info --format '{{.NCPU}}') || {
    echo 'Cannot detect Docker host CPUs; no Compose operation was performed.' >&2
    exit 1
}
case "$logical_cpus" in
    ''|*[!0-9]*)
        echo 'Docker returned an invalid logical CPU count; refusing to start without a CPU limit.' >&2
        exit 1 ;;
esac
if [ "$logical_cpus" -le 1 ]; then
    echo 'At least two logical CPUs are required to leave one CPU for Tango.' >&2
    exit 1
fi
# Always override old shell/.env limits with the value for the current Docker host.
LOGCOMPARATOR_CPU_LIMIT=$((logical_cpus - 1))
export LOGCOMPARATOR_CPU_LIMIT
printf 'Docker host: %s logical CPUs; LogComparator limit: %s; Tango allowance: 1.\n' "$logical_cpus" "$LOGCOMPARATOR_CPU_LIMIT" >&2
exec docker compose "$@"
