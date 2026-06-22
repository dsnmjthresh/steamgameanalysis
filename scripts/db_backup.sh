#!/usr/bin/env bash
# =============================================================================
# SteamAnalysis — SQLite database backup script (Linux / macOS / Docker host)
# =============================================================================
# Produces a point-in-time backup of a SQLite database, including its WAL and
# SHM companion files.  Designed for both interactive and cron use.
#
# Usage:
#   ./scripts/db_backup.sh -d /app/data/steamanalysis.sqlite3 -o /backups
#   ./scripts/db_backup.sh -d ./steamanalysis.sqlite3 -o ./backups -r 30 --dry-run
#   ./scripts/db_backup.sh -d /app/data/steamanalysis.sqlite3 -o /backups -r 7 -n
#     (create backup; keep 7 days; skip WAL checkpoint)
#
# Options:
#   -d PATH   Path to the live SQLite database file (required).
#   -o DIR    Directory where backup files will be written (required).
#   -r DAYS   Delete backup sets older than this many days (default: 7).
#   -n        Skip WAL checkpoint before copy.
#   -N        Skip old-backup cleanup (retention).
#   --dry-run Show what would be done without actually doing it.
#   -h        Show this help message.
#
# Output (per run, inside output dir):
#   <db_base>_<UTC_ISO>.backup.sqlite3          – main database
#   <db_base>_<UTC_ISO>.backup.sqlite3-wal      – WAL (if non-empty after checkpoint)
#   <db_base>_<UTC_ISO>.backup.sqlite3-shm      – SHM (if non-empty after checkpoint)
#   <db_base>_<UTC_ISO>.backup.manifest.json    – metadata + checksums
#
# Exit codes: 0 = success, 1 = usage, 2 = source not found,
#             3 = backup failure, 4 = cleanup warning (backup succeeded).
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

cleanup_on_interrupt() {
    log_warn "Backup interrupted (SIGINT/SIGTERM). Partial files may be present in $OUTPUT_DIR."
    exit 3
}

trap cleanup_on_interrupt INT TERM

# ---- defaults ----

DB_PATH=""
OUTPUT_DIR=""
RETENTION_DAYS=7
NO_CHECKPOINT=false
NO_RETENTION=false
DRY_RUN=false

# ---- arg parsing ----

while [[ $# -gt 0 ]]; do
    case "$1" in
        -d) DB_PATH="$2"; shift 2 ;;
        -o) OUTPUT_DIR="$2"; shift 2 ;;
        -r) RETENTION_DAYS="$2"; shift 2 ;;
        -n) NO_CHECKPOINT=true; shift ;;
        -N) NO_RETENTION=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help) usage ;;
        *) log_error "Unknown option: $1"; usage ;;
    esac
done

# ---- validation ----

if [[ -z "$DB_PATH" ]]; then
    log_error "Missing required option: -d DATABASE_PATH"
    usage
fi
if [[ -z "$OUTPUT_DIR" ]]; then
    log_error "Missing required option: -o OUTPUT_DIR"
    usage
fi
if [[ ! -f "$DB_PATH" ]]; then
    log_error "Database file not found: $DB_PATH"
    exit 2
fi
if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || [[ "$RETENTION_DAYS" -lt 1 ]] || [[ "$RETENTION_DAYS" -gt 365 ]]; then
    log_error "Retention days must be an integer between 1 and 365, got: $RETENTION_DAYS"
    exit 1
fi

# Normalise to absolute paths
DB_PATH="$(realpath "$DB_PATH")"
OUTPUT_DIR="$(realpath -m "$OUTPUT_DIR")"  # -m: don't require existence yet

DB_FILENAME="$(basename "$DB_PATH")"                        # e.g. steamanalysis.sqlite3
DB_BASENAME="${DB_FILENAME%.*}"                              # e.g. steamanalysis  (strip last extension)
TIMESTAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
BACKUP_PREFIX="${DB_BASENAME}_${TIMESTAMP}.backup"

WAL_PATH="${DB_PATH}-wal"
SHM_PATH="${DB_PATH}-shm"

# ---- dry-run banner ----

if [[ "$DRY_RUN" == "true" ]]; then
    echo ""
    echo "========== DRY-RUN MODE — no changes will be made =========="
    echo ""
fi

log_info "=== SteamAnalysis DB Backup ==="
log_info "Source database : $DB_PATH"
log_info "Output directory: $OUTPUT_DIR"
log_info "Retention days  : $RETENTION_DAYS"
log_info "Dry run         : $DRY_RUN"

# ===========================================================================
# 1. Create output directory
# ===========================================================================
if [[ "$DRY_RUN" == "true" ]]; then
    if [[ ! -d "$OUTPUT_DIR" ]]; then
        log_info "[DRYRUN] Would create directory: $OUTPUT_DIR"
    fi
else
    mkdir -p "$OUTPUT_DIR"
    log_info "Output directory ready: $OUTPUT_DIR"
fi

# ===========================================================================
# 2. WAL checkpoint
# ===========================================================================
if [[ "$NO_CHECKPOINT" == "false" ]]; then
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRYRUN] Would run: sqlite3 $DB_PATH \"PRAGMA wal_checkpoint(TRUNCATE)\""
    else
        if command -v sqlite3 &>/dev/null; then
            log_info "Running WAL checkpoint (TRUNCATE) …"
            if result=$(sqlite3 "$DB_PATH" "PRAGMA wal_checkpoint(TRUNCATE);" 2>&1); then
                log_info "Checkpoint result: $result"
            else
                log_warn "TRUNCATE checkpoint failed; trying PASSIVE …"
                result=$(sqlite3 "$DB_PATH" "PRAGMA wal_checkpoint(PASSIVE);" 2>&1) || true
                log_info "PASSIVE checkpoint result: $result"
            fi
        else
            log_warn "sqlite3 CLI not found — skipping WAL checkpoint. Backup captures current on-disk state."
        fi
    fi
else
    log_warn "WAL checkpoint skipped (-n). Backup captures current on-disk state."
fi

# ===========================================================================
# 3. Copy database files
# ===========================================================================
DEST_MAIN="${OUTPUT_DIR}/${BACKUP_PREFIX}.sqlite3"
DEST_WAL="${OUTPUT_DIR}/${BACKUP_PREFIX}.sqlite3-wal"
DEST_SHM="${OUTPUT_DIR}/${BACKUP_PREFIX}.sqlite3-shm"

copied_files=()

copy_db_file() {
    local src="$1"
    local dst="$2"
    local label="$3"

    if [[ ! -f "$src" ]]; then
        log_info "$label: file not present, skipping."
        return 1
    fi

    local size
    size=$(stat -c%s "$src" 2>/dev/null || stat -f%z "$src" 2>/dev/null || echo 0)

    if [[ "$size" -eq 0 ]]; then
        log_info "$label: file is empty (0 bytes), skipping."
        return 1
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRYRUN] Would copy: $src -> $dst ($size bytes)"
        copied_files+=("${label}|${dst}")
        return 0
    fi

    cp "$src" "$dst"
    log_info "$label: copied ($size bytes)"
    copied_files+=("${label}|${dst}")
    return 0
}

copy_db_file "$DB_PATH"  "$DEST_MAIN" "Main DB"
copy_db_file "$WAL_PATH" "$DEST_WAL"  "WAL file"
copy_db_file "$SHM_PATH" "$DEST_SHM"  "SHM file"

if [[ ${#copied_files[@]} -eq 0 ]]; then
    log_error "No files were copied — backup ABORTED."
    exit 3
fi

# ===========================================================================
# 4. Generate manifest
# ===========================================================================
MANIFEST_PATH="${OUTPUT_DIR}/${BACKUP_PREFIX}.manifest.json"

generate_manifest() {
    local ts="$1"
    local host="${HOSTNAME:-$(hostname 2>/dev/null || echo 'unknown')}"
    local now
    now=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

    echo '{'
    echo "  \"backup_timestamp_utc\": \"${ts}\","
    echo "  \"generated_at_utc\": \"${now}\","
    echo "  \"source_database_path\": \"${DB_PATH}\","
    echo "  \"hostname\": \"${host}\","
    echo "  \"script_version\": \"1.0.0\","
    echo "  \"wal_checkpoint\": $([[ "$NO_CHECKPOINT" == "false" ]] && echo 'true' || echo 'false'),"
    echo '  "files": ['

    local first=true
    for entry in "${copied_files[@]}"; do
        local label="${entry%%|*}"
        local fpath="${entry#*|}"
        local fname
        fname="$(basename "$fpath")"
        local sha=""
        local fsize=0
        if [[ "$DRY_RUN" != "true" ]]; then
            sha=$(sha256sum "$fpath" | awk '{print $1}')
            fsize=$(stat -c%s "$fpath" 2>/dev/null || stat -f%z "$fpath" 2>/dev/null || echo 0)
        fi

        if [[ "$first" == "true" ]]; then first=false; else echo '    ,'; fi
        echo -n '    {'
        echo -n "\"label\": \"${label}\""
        echo -n ", \"filename\": \"${fname}\""
        echo -n ", \"size_bytes\": ${fsize}"
        if [[ "$DRY_RUN" != "true" ]]; then
            echo -n ", \"sha256\": \"${sha}\""
        fi
        echo -n '}'
    done

    echo ''
    echo '  ]'
    echo '}'
}

if [[ "$DRY_RUN" == "true" ]]; then
    log_info "[DRYRUN] Would write manifest: $MANIFEST_PATH"
    log_info "[DRYRUN] Manifest content:"
    generate_manifest "$TIMESTAMP"
else
    generate_manifest "$TIMESTAMP" > "$MANIFEST_PATH"
    log_info "Manifest written: $MANIFEST_PATH"
fi

# ===========================================================================
# 5. Clean up old backups
# ===========================================================================
if [[ "$NO_RETENTION" == "false" ]]; then
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRYRUN] Would remove backup files older than $RETENTION_DAYS day(s) from $OUTPUT_DIR"
        find "$OUTPUT_DIR" -maxdepth 1 -type f -name "${DB_BASENAME}_*.backup.*" -mtime "+${RETENTION_DAYS}" -print 2>/dev/null | while read -r f; do
            log_info "[DRYRUN] Would remove: $(basename "$f")"
        done
    else
        log_info "Cleaning backups older than $RETENTION_DAYS day(s) …"
        old_files=$(find "$OUTPUT_DIR" -maxdepth 1 -type f -name "${DB_BASENAME}_*.backup.*" -mtime "+${RETENTION_DAYS}" -print 2>/dev/null)
        if [[ -n "$old_files" ]]; then
            count=0
            while read -r f; do
                log_info "Removing old backup: $(basename "$f")"
                rm -f "$f"
                ((count++)) || true
            done <<< "$old_files"
            log_info "Removed $count old backup file(s)."
        else
            log_info "No old backups to remove."
        fi
    fi
else
    log_info "Retention cleanup skipped (-N)."
fi

# ===========================================================================
# 6. Report
# ===========================================================================
echo ""
echo "========== Backup completed =========="
echo "Timestamp  : $TIMESTAMP"
echo "Output dir : $OUTPUT_DIR"
echo "Files      :"
for entry in "${copied_files[@]}"; do
    echo "  ${entry#*|}"
done
echo "Manifest   : $MANIFEST_PATH"
echo ""
exit 0
