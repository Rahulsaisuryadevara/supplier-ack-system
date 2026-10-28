#!/usr/bin/env bash
# Reproducible end-to-end reviewer demo. Run from any directory with bash scripts/demo.sh.
set -uo pipefail
# Ensure Unicode arrows and other report characters print consistently on Windows
# terminals using Git Bash as well as on Unix-like systems.
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STATUS=0
declare -a RESULTS=()
run_step() {
  local label="$1"; shift
  printf '\n\n============================================================\n'
  printf 'STEP: %s\n' "$label"
  printf 'COMMAND:'; printf ' %q' "$@"; printf '\n------------------------------------------------------------\n'
  if "$@"; then
    printf '\n[PASS] %s\n' "$label"
    RESULTS+=("PASS | $label")
  else
    local rc=$?
    printf '\n[FAIL] %s (exit %s)\n' "$label" "$rc"
    RESULTS+=("FAIL | $label (exit $rc)")
    STATUS=1
  fi
}

PYTHON="${PYTHON:-python}"
run_step "Generate starter dataset + reconciliation + validation" \
  "$PYTHON" -m supplier_ack.cli generate --config config/generator_config.yaml --scale starter --seed 20261022
run_step "Export CSV, JSON, SQL and committed demo database" \
  "$PYTHON" -m supplier_ack.cli export --dataset data/samples --formats csv,json,sql --out data/samples
run_step "Validate all starter tables" \
  "$PYTHON" -m supplier_ack.cli validate --dataset data/samples
run_step "Detect labelled anomalies without label leakage" \
  "$PYTHON" -m supplier_ack.cli detect --dataset data/samples --out reports/starter/detection_report.md
run_step "Build persona reports and data-quality report" \
  "$PYTHON" -m supplier_ack.cli report --dataset data/samples --out reports/starter
DEMO_DB="$("$PYTHON" -c 'import tempfile; f=tempfile.NamedTemporaryFile(prefix="supplier-ack-demo-", suffix=".db", delete=False); print(f.name); f.close()')"
cp data/samples/demo.db "$DEMO_DB"
trap 'rm -f "$DEMO_DB"' EXIT
run_step "Process demo live events on a disposable copy of the committed demo database" \
  "$PYTHON" -m supplier_ack.cli workflow run --db "$DEMO_DB" --events data/samples/demo_events.json

printf '\n\n====================== DEMO SUMMARY ======================\n'
for result in "${RESULTS[@]}"; do printf '%s\n' "$result"; done
if [[ "$STATUS" -eq 0 ]]; then
  printf '\nOVERALL: PASS — all demo steps completed.\n'
else
  printf '\nOVERALL: FAIL — review the failed step(s) above.\n'
fi
exit "$STATUS"
