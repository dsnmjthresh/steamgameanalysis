#!/usr/bin/env bash
# =============================================================================
# SteamAnalysis — SQLite database restore script (Linux / macOS / Docker host)
# =============================================================================
# Restores a SQLite database from a backup set produced by db_backup.sh.
# By default the script REFUSES to overwrite an existing file at the target
# path.  Use --force to override, or run interactively and confirm the prompt.
#
# Usage:
#   ./scripts/db_restore.sh -b ./backups/steamanalysis_20260609T120000Z.backup.sqlite3 -t ./restored.sqlite3
#   ./scripts/db_restore.sh -b ./backups/steamanalysis_20260609T120000Z.backup.sqlite3 -t ./restored.sqlite3 --force
#   ./scripts/db_restore.sh -b ./backups/steamanalysis_20260609T120000Z.backup.sqlite3 -t ./restored.sqlite3 --dry-run
#
# Options:
#   -b PATH    Path to the backed-up .sqlite3 file (required).
#   -t PATH    Target path for the restored database (required).
#   --force    Overwrite an existing file without prompting.
#   --dry-run  Show what would be done without actually doing it.
#   --skip-integrity  Skip the post-restore integrity check.
#   -h         Show this help message.
#
# Exit codes: 0 = success, 1 = usage, 2 = backup not found,
#             3 = target exists and was refused, 4 = integrity check failed,
#             5 = restore failure.
# =============================================================================

set -uo pipefail

# ---- helpers ----

log_info()  { echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] [INFO ] $*"; }
log_warn()  { echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] [WARN ] $*" >&2; }
log_error() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" >&2; }

usage() {
    sed -n '/^# =/,/^# =/p' "$0" | grep -E '^#( |$)' | sed 's/^# \?//'
    exit 1
}

# ---- defaults ----

BACKUP_FILE=""
TARGET_PATH=""
FORCE=false
DRY_RUN=false
SKIP_INTEGRITY=false

# ---- arg parsing ----

while [[ $# -gt 0 ]]; do
    case "$1" in
        -b) BACKUP_FILE="$2"; shift 2 ;;
        -t) TARGET_PATH="$2"; shift 2 ;;
        --force) FORCE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --skip-integrity) SKIP_INTEGRITY=true; shift ;;
        -h|--help) usage ;;
        *) log_error "Unknown option: $1"; usage ;;
    esac
done

# ---- validation ----

if [[ -z "$BACKUP_FILE" ]]; then
    log_error "Missing required option: -b BACKUP_FILE"
    usage
fi
if [[ -z "$TARGET_PATH" ]]; then
    log_error "Missing required option: -t TARGET_PATH"
    usage
fi
if [[ ! -f "$BACKUP_FILE" ]]; then
    log_error "Backup file not found: $BACKUP_FILE"
    exit 2
fi

# Normalise to absolute paths
BACKUP_FILE="$(realpath "$BACKUP_FILE")"
TARGET_PATH="$(realpath -m "$TARGET_PATH")"
TARGET_DIR="$(dirname "$TARGET_PATH")"

# ---- dry-run banner ----

if [[ "$DRY_RUN" == "true" ]]; then
    echo ""
    echo "========== DRY-RUN MODE — no changes will be made =========="
    echo ""
fi

log_info "=== SteamAnalysis DB Restore ==="
log_info "Backup file : $BACKUP_FILE"
log_info "Target path : $TARGET_PATH"
log_info "Target dir  : $TARGET_DIR"
log_info "Force       : $FORCE"
log_info "Dry run     : $DRY_RUN"

# ===========================================================================
# 1. Locate companion files
# ===========================================================================
BACKUP_DIR="$(dirname "$BACKUP_FILE")"
BACKUP_BASENAME="$(basename "$BACKUP_FILE")"
# Strip ".sqlite3" suffix to get the backup prefix
BACKUP_PREFIX="${BACKUP_BASENAME%.sqlite3}"

WAL_SRC="${BACKUP_DIR}/${BACKUP_PREFIX}.sqlite3-wal"
SHM_SRC="${BACKUP_DIR}/${BACKUP_PREFIX}.sqlite3-shm"
MANIFEST_SRC="${BACKUP_DIR}/${BACKUP_PREFIX}.manifest.json"

log_info "Companion files:"
log_info "  WAL     : $WAL_SRC  $( [[ -f "$WAL_SRC" ]] && echo '(exists)' || echo '(not found)' )"
log_info "  SHM     : $SHM_SRC  $( [[ -f "$SHM_SRC" ]] && echo '(exists)' || echo '(not found)' )"
log_info "  Manifest: $MANIFEST_SRC  $( [[ -f "$MANIFEST_SRC" ]] && echo '(exists)' || echo '(not found)' )"

# ===========================================================================
# 2. Display manifest if available
# ===========================================================================
if [[ -f "$MANIFEST_SRC" ]]; then
    if command -v python3 &>/dev/null; then
        log_info "Manifest summary:"
        python3 -c "
import json, sys
try:
    m = json.load(open('$MANIFEST_SRC'))
    print(f\"  Backup timestamp : {m.get('backup_timestamp_utc', 'N/A')}\")
    print(f\"  Source database  : {m.get('source_database_path', 'N/A')}\")
    print(f\"  Hostname         : {m.get('hostname', 'N/A')}\")
    print(f\"  WAL checkpointed : {m.get('wal_checkpoint', 'N/A')}\")
except Exception as e:
    print(f'  (could not parse: {e})', file=sys.stderr)
" 2>&1 || true
    else
        log_info "Manifest present but python3 not available for summary."
    fi
fi

# ===========================================================================
# 3. Pre-flight: target conflict check
# ===========================================================================
if [[ -f "$TARGET_PATH" ]]; then
    target_size=$(stat -c%s "$TARGET_PATH" 2>/dev/null || stat -f%z "$TARGET_PATH" 2>/dev/null || echo 0)
    log_warn "Target file already exists: $TARGET_PATH ($target_size bytes)"

    if [[ "$FORCE" == "true" ]]; then
        log_info "--force specified — will overwrite."
    elif [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRYRUN] Target exists — would prompt for overwrite (or honour --force)."
    else
        read -r -p "Overwrite existing file? [y/N] " response
        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            log_error "Restore ABORTED by user — target exists and overwrite was denied."
            exit 3
        fi
        log_info "User confirmed overwrite."
    fi
fi

# ===========================================================================
# 4. Create target directory if needed
# ===========================================================================
if [[ "$DRY_RUN" == "true" ]]; then
    if [[ ! -d "$TARGET_DIR" ]]; then
        log_info "[DRYRUN] Would create target directory: $TARGET_DIR"
    fi
else
    if [[ ! -d "$TARGET_DIR" ]]; then
        log_info "Creating target directory: $TARGET_DIR"
        mkdir -p "$TARGET_DIR"
    fi
fi

# ===========================================================================
# 5. Copy restored files
# ===========================================================================
TARGET_WAL="${TARGET_PATH}-wal"
TARGET_SHM="${TARGET_PATH}-shm"

restored_files=()

restore_file() {
    local src="$1"
    local dst="$2"
    local label="$3"

    if [[ ! -f "$src" ]]; then
        log_info "$label: source not present, skipping."
        return 1
    fi

    local src_size
    src_size=$(stat -c%s "$src" 2>/dev/null || stat -f%z "$src" 2>/dev/null || echo 0)

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRYRUN] Would copy: $src -> $dst ($src_size bytes)"
        restored_files+=("${label}|${dst}")
        return 0
    fi

    cp "$src" "$dst"
    local dst_size
    dst_size=$(stat -c%s "$dst" 2>/dev/null || stat -f%z "$dst" 2>/dev/null || echo 0)
    log_info "$label: restored ($dst_size bytes)"
    restored_files+=("${label}|${dst}")
    return 0
}

restore_file "$BACKUP_FILE" "$TARGET_PATH" "Main DB"
restore_file "$WAL_SRC"      "$TARGET_WAL"  "WAL file"
restore_file "$SHM_SRC"      "$TARGET_SHM"  "SHM file"

if [[ ${#restored_files[@]} -eq 0 ]]; then
    log_error "No files were restored — ABORTED."
    exit 5
fi

# ===========================================================================
# 6. Compute and display checksums
# ===========================================================================
log_info "Checksums (SHA256):"
for entry in "${restored_files[@]}"; do
    label="${entry%%|*}"
    fpath="${entry#*|}"
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "  $label: (dry-run)"
    else
        sha=$(sha256sum "$fpath" | awk '{print $1}')
        log_info "  $label: $sha"
    fi
done

# ===========================================================================
# 7. Integrity check
# ===========================================================================
if [[ "$SKIP_INTEGRITY" == "false" ]]; then
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRYRUN] Would run: sqlite3 $TARGET_PATH \"PRAGMA integrity_check\""
    else
        if command -v sqlite3 &>/dev/null; then
            echo ""
            log_info "Running integrity_check …"
            if result=$(sqlite3 "$TARGET_PATH" "PRAGMA integrity_check;" 2>&1); then
                if echo "$result" | grep -qi '^ok$'; then
                    log_info "Integrity check PASSED: $result"
                else
                    log_error "Integrity check FAILED: $result"
                    log_error "The restored database may be corrupt."
                    log_error "You should delete $TARGET_PATH and retry with a different backup."
                    exit 4
                fi
            else
                log_error "Integrity check FAILED with error."
                exit 4
            fi
        else
            log_warn "sqlite3 CLI not found — skipping integrity check."
        fi
    fi
else
    log_warn "Integrity check skipped (--skip-integrity)."
fi

# ===========================================================================
# 8. Checkpoint restored WAL into main DB
# ===========================================================================
if [[ "$DRY_RUN" != "true" ]] && [[ -f "$TARGET_WAL" ]]; then
    if command -v sqlite3 &>/dev/null; then
        log_info "Restored DB has WAL file — running checkpoint to merge …"
        sqlite3 "$TARGET_PATH" "PRAGMA wal_checkpoint(TRUNCATE);" 2>&1 || true
        log_info "WAL checkpointed into restored DB."
        # Clean up WAL/SHM if now zero-length
        if [[ -f "$TARGET_WAL" ]] && [[ ! -s "$TARGET_WAL" ]]; then
            rm -f "$TARGET_WAL"
            log_info "Removed zero-length restored WAL file."
        fi
        if [[ -f "$TARGET_SHM" ]]; then
            rm -f "$TARGET_SHM"
            log_info "Removed restored SHM file."
        fi
    fi
fi

# ===========================================================================
# 9. Report
# ===========================================================================
echo ""
echo "========== Restore completed =========="
echo "Target       : $TARGET_PATH"
echo "Files restored:"
for entry in "${restored_files[@]}"; do
    echo "  ${entry%%|*}: ${entry#*|}"
done

# ===========================================================================
# 10. Usage hint
# ===========================================================================
echo ""
echo "Next steps:"
echo "  export STEAMANALYSIS_DATABASE_URL=\"sqlite:///$TARGET_PATH\""
echo "  # or update your .env file:"
echo "  # STEAMANALYSIS_DATABASE_URL=sqlite:///$TARGET_PATH"
echo ""
exit 0
