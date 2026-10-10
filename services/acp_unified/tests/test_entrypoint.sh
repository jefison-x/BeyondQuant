#!/bin/sh
# BYQ ACP unified-image entrypoint targeted test (no Docker, no real secrets).
#
# Drives the real services/acp_unified/entrypoint.sh with a stubbed `id` on PATH
# so the adapter identity guard and the fail-closed role dispatcher can be
# exercised without Docker, root, a container runtime, or any real secret.
#
# Proves:
#   - an unset BYQ_ACP_ROLE is refused (exit 64)
#   - an unknown BYQ_ACP_ROLE is refused (exit 64)
#   - the adapter role refuses a mismatched effective uid and/or gid (exit 77)
#     and never reaches the uvicorn exec
#   - the adapter role clears the identity guard only for 10002:10002
set -u

here=$(cd "$(dirname "$0")" && pwd)
entrypoint="$here/../entrypoint.sh"

if [ ! -f "$entrypoint" ]; then
  echo "entrypoint.sh not found at $entrypoint" >&2
  exit 2
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT INT TERM
mkdir -p "$work/bin"

cat > "$work/bin/id" <<'STUB'
#!/bin/sh
# Effective-id stub: entrypoint.sh calls `id -u` / `id -g`.
case "${1:-}" in
  -u) printf '%s\n' "${BYQ_TEST_UID:?BYQ_TEST_UID unset}" ;;
  -g) printf '%s\n' "${BYQ_TEST_GID:?BYQ_TEST_GID unset}" ;;
  *)  printf '%s\n' "${BYQ_TEST_UID:?BYQ_TEST_UID unset}" ;;
esac
STUB
chmod 0755 "$work/bin/id"

pass=0
fail=0
note() { printf '%s\n' "$*"; }
check() { # check <label> <expected-exit> <actual-exit> <output> <regex>
  label=$1; expected=$2; actual=$3; output=$4; regex=$5
  if [ "$actual" = "$expected" ] && printf '%s' "$output" | grep -Eq "$regex"; then
    note "[PASS] $label (exit=$actual)"
    pass=$((pass + 1))
  else
    note "[FAIL] $label expected exit=$expected regex=/$regex/ got exit=$actual"
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
  fi
}

run_case() { # run_case <role|UNSET> <uid> <gid>  -> sets $out, $code
  if [ "$1" = "UNSET" ]; then
    out=$(PATH="$work/bin:$PATH" BYQ_TEST_UID="$2" BYQ_TEST_GID="$3" \
          env -u BYQ_ACP_ROLE sh "$entrypoint" 2>&1)
  else
    out=$(PATH="$work/bin:$PATH" BYQ_TEST_UID="$2" BYQ_TEST_GID="$3" \
          BYQ_ACP_ROLE="$1" sh "$entrypoint" 2>&1)
  fi
  code=$?
}

note "== role dispatcher =="
run_case UNSET 10002 10002
check "unset BYQ_ACP_ROLE refused" 64 "$code" "$out" "BYQ_ACP_ROLE must be one of"
run_case bogus 10002 10002
check "unknown BYQ_ACP_ROLE refused" 64 "$code" "$out" "BYQ_ACP_ROLE must be one of"

note ""
note "== adapter identity guard =="
run_case adapter 0 0
check "adapter as root refused" 77 "$code" "$out" "must run as byq"
run_case adapter 10002 0
check "adapter wrong gid refused" 77 "$code" "$out" "must run as byq"
run_case adapter 0 10002
check "adapter wrong uid refused" 77 "$code" "$out" "must run as byq"
run_case adapter 1234 1234
check "adapter unknown identity refused" 77 "$code" "$out" "must run as byq"

run_case adapter 10002 10002
# The guard must NOT fire; the adapter proceeds to `cd /app` + exec uvicorn,
# which is absent on the test host, so exit is non-zero but never 77 and never
# the guard message.
if [ "$code" != "77" ] && ! printf '%s' "$out" | grep -q "must run as byq"; then
  note "[PASS] adapter 10002:10002 clears the identity guard"
  pass=$((pass + 1))
else
  note "[FAIL] adapter 10002:10002 should clear the guard (exit=$code)"
  printf '%s\n' "$out" | sed 's/^/    /'
  fail=$((fail + 1))
fi

note ""
note "== SUMMARY =="
note "PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
