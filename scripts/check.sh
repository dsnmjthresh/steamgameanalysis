#!/usr/bin/env bash
# SteamAnalysis CI check script (Linux / macOS)
# Usage: ./scripts/check.sh
# Runs: backend tests, evals, ruff, mypy, frontend typecheck, lint, build, fresh DB migration
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

# Detect Python in virtual environment (Windows .venv/Scripts or POSIX .venv/bin)
if [[ -x "$BACKEND_DIR/.venv/Scripts/python" ]]; then
  PYTHON_EXE="$BACKEND_DIR/.venv/Scripts/python"
elif [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  PYTHON_EXE="$BACKEND_DIR/.venv/bin/python"
else
  echo "Error: Python not found in backend/.venv. Create a virtual env first."
  exit 1
fi

# Colour helpers (no-op if not a TTY)
if [[ -t 1 ]]; then
  BOLD="$(tput bold 2>/dev/null || true)"
  GREEN="$(tput setaf 2 2>/dev/null || true)"
  RED="$(tput setaf 1 2>/dev/null || true)"
  YELLOW="$(tput setaf 3 2>/dev/null || true)"
  CYAN="$(tput setaf 6 2>/dev/null || true)"
  RESET="$(tput sgr0 2>/dev/null || true)"
else
  BOLD="" GREEN="" RED="" YELLOW="" CYAN="" RESET=""
fi

FAILED=()

# ── Helpers ────────────────────────────────────────────────────────────
step() {
  echo ""
  echo "${CYAN}=== $* ===${RESET}"
}

run_check() {
  local name="$1"
  local workdir="$2"
  local cmd="$3"
  shift 3
  step "$name"
  if (cd "$workdir" && "$cmd" "$@"); then
    echo "  ${GREEN}PASSED${RESET}"
  else
    local rc=$?
    echo "  ${RED}FAILED (exit $rc)${RESET}"
    FAILED+=("$name")
  fi
}

# ── Backend ────────────────────────────────────────────────────────────
echo "${YELLOW}${BOLD}====== Backend Checks ======${RESET}"

run_check "backend-tests"       "$BACKEND_DIR" "$PYTHON_EXE" -m pytest app/tests -q --tb=short
run_check "backend-evals"       "$BACKEND_DIR" "$PYTHON_EXE" -m pytest app/evals -q --tb=short
run_check "backend-ruff"        "$BACKEND_DIR" "$PYTHON_EXE" -m ruff check app
run_check "backend-mypy"        "$BACKEND_DIR" "$PYTHON_EXE" -m mypy app

# ── Frontend ───────────────────────────────────────────────────────────
echo ""
echo "${YELLOW}${BOLD}====== Frontend Checks ======${RESET}"

run_check "frontend-tests"      "$FRONTEND_DIR" npm run test:unit -- --run
run_check "frontend-typecheck"  "$FRONTEND_DIR" npm run typecheck
run_check "frontend-lint"       "$FRONTEND_DIR" npm run lint
run_check "frontend-build"      "$FRONTEND_DIR" npm run build

# ── DB Migration Smoke Test ────────────────────────────────────────────
echo ""
echo "${YELLOW}${BOLD}====== DB Migration Smoke Test ======${RESET}"

TMP_DB="${TMPDIR:-/tmp}/steamanalysis_alembic_fresh_test_$$.sqlite3"
rm -f "$TMP_DB"

step "db-migration"
export STEAMANALYSIS_DATABASE_URL="sqlite:///${TMP_DB}"
if (cd "$BACKEND_DIR" && "$PYTHON_EXE" -m alembic upgrade head); then
  echo "  ${GREEN}DB Migration PASSED${RESET}"
else
  rc=$?
  echo "  ${RED}DB Migration FAILED (exit $rc)${RESET}"
  FAILED+=("db-migration")
fi
rm -f "$TMP_DB"

# ── Summary ────────────────────────────────────────────────────────────
echo ""
echo "${YELLOW}${BOLD}====== Summary ======${RESET}"
if [[ ${#FAILED[@]} -eq 0 ]]; then
  echo "${GREEN}${BOLD}All checks PASSED!${RESET}"
  exit 0
else
  echo "${RED}${BOLD}FAILED: ${FAILED[*]}${RESET}"
  exit 1
fi
