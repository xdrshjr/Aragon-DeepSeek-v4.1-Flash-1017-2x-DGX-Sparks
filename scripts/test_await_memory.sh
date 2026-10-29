#!/usr/bin/env bash
# Regression test for await_memory (scripts/nodes.sh, MIN_AVAIL_WAIT_S): takes the function out of nodes.sh and drives it with
# stubs for mem_available_gib, worker and sleep. Run: bash scripts/test_await_memory.sh
set -uo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
eval "$(awk '/^await_memory\(\) \{/ {on=1} on {print} on && /^\}/ {exit}' "$here/nodes.sh")"
declare -F await_memory >/dev/null || { echo "FAIL: await_memory is not defined in nodes.sh"; exit 1; }
sleep() { :; }
# both stubs run in $( ) subshells, so the reading count lives in a file
fails=0; counter=$(mktemp); trap 'rm -f "$counter"' EXIT
pick() { local -n a=$1; local n; n=$(<"$counter"); echo "${a[$(( n < ${#a[@]} ? n : ${#a[@]} - 1 ))]}"; }
mem_available_gib() { pick HERE_SEQ; }
worker() { pick WORK_SEQ; echo $(( $(<"$counter") + 1 )) >"$counter"; }
reset() { echo 0 >"$counter"; }
check() { reads=$(<"$counter"); # name expected_rc expected_reads
  if [[ "$rc" == "$2" && "$reads" == "$3" ]]; then echo "ok   $1"; else echo "FAIL $1: rc=$rc (want $2), reads=$reads (want $3)"; fails=$((fails + 1)); fi
}
MIN_AVAIL_GIB=112

MIN_AVAIL_WAIT_S=30; HERE_SEQ=(119.0); WORK_SEQ=(119.0); reset; await_memory; rc=$?
check "both enough: one reading" 0 1
MIN_AVAIL_WAIT_S=30; HERE_SEQ=(119.0); WORK_SEQ=(111.1 110.4 119.0); reset; await_memory; rc=$?
check "worker settles on the third reading" 0 3
MIN_AVAIL_WAIT_S=30; HERE_SEQ=(119.0); WORK_SEQ=(100.0); reset; await_memory; rc=$?
check "never enough: gives up after 30 s / 2 + 1 readings" 1 16
MIN_AVAIL_WAIT_S=0; HERE_SEQ=(119.0); WORK_SEQ=(100.0); reset; await_memory; rc=$?
check "MIN_AVAIL_WAIT_S=0 reads once" 1 1
exit $(( fails > 0 ))
