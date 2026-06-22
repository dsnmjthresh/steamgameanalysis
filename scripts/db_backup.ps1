# SteamAnalysis - SQLite database backup script (PowerShell)
# =============================================================================
# Produces a point-in-time backup of a SQLite database, including its WAL
# and SHM companion files.
#
# Usage:
#   .\scripts\db_backup.ps1 -DatabasePath .\steamanalysis.sqlite3 -BackupDir .\backups
#   .\scripts\db_backup.ps1 -DatabasePath .\steamanalysis.sqlite3 -BackupDir .\backups -RetentionDays 30 -DryRun
#
# Exit codes: 0 = success, 1 = usage / argument error, 2 = source not found,
#             3 = backup failure, 4 = cleanup warning (backup succeeded).
# =============================================================================

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, HelpMessage = "Path to the live SQLite database file")]
    [ValidateScript({
        if (-not (Test-Path -LiteralPath $_ -PathType Leaf)) {
            throw "Database file not found: $_"
        }
        $true
    })]
    [string]$DatabasePath,

    [Parameter(Mandatory = $true, HelpMessage = "Directory for backup files")]
    [string]$BackupDir,

    [Parameter(HelpMessage = "Delete backup sets older than N days")]
    [ValidateRange(1, 365)]
    [int]$RetentionDays = 7,

    [Parameter(HelpMessage = "Show actions without executing")]
    [switch]$DryRun,

    [Parameter(HelpMessage = "Skip WAL checkpoint before copy")]
    [switch]$NoCheckpoint,

    [Parameter(HelpMessage = "Skip old-backup cleanup")]
    [switch]$NoRetention
)

$ErrorActionPreference = "Continue"
$ScriptName = [System.IO.Path]::GetFileName($MyInvocation.MyCommand.Path)
# Capture script root at top level — $MyInvocation is unreliable inside functions
$ScriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

function Write-BackupInfo {
    param([string]$Message)
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [INFO ] ${Message}"
}

function Write-BackupWarn {
    param([string]$Message)
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [WARN ] ${Message}" -ForegroundColor Yellow
}

function Write-BackupError {
    param([string]$Message)
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [ERROR] ${Message}" -ForegroundColor Red
}

function Get-UtcTimestamp {
    return (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
}

function Get-Sqlite3Cli {
    $candidates = @(
        "sqlite3",
        "sqlite3.exe",
        (Join-Path $env:ProgramFiles "sqlite3.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "sqlite3.exe")
    )
    foreach ($c in $candidates) {
        $found = Get-Command $c -CommandType Application -ErrorAction SilentlyContinue
        if ($found) {
            try {
                $null = & $found.Source "--version" 2>&1
                return $found.Source
            } catch { }
        }
    }
    return $null
}

function Invoke-WalCheckpoint {
    param([string]$DbPath)

    $sqliteCli = Get-Sqlite3Cli

    if ($sqliteCli) {
        Write-BackupInfo "Running WAL checkpoint via sqlite3 CLI (${sqliteCli})"
        $result = & $sqliteCli $DbPath "PRAGMA wal_checkpoint(TRUNCATE);" 2>&1
        Write-BackupInfo "Checkpoint result: ${result}"
        if ($LASTEXITCODE -ne 0) {
            Write-BackupWarn "TRUNCATE checkpoint failed - trying PASSIVE"
            $result = & $sqliteCli $DbPath "PRAGMA wal_checkpoint(PASSIVE);" 2>&1
            Write-BackupInfo "PASSIVE checkpoint result: ${result}"
        }
        return
    }

    # Fallback: try environment variable, then project Python venv, then system python
    $projectRoot = Split-Path -Parent (Split-Path -Parent $Script:ScriptRoot)
    $pythonCandidates = @()
    if ($env:STEAMANALYSIS_PYTHON) {
        $pythonCandidates += $env:STEAMANALYSIS_PYTHON
    }
    $pythonCandidates += @(
        (Join-Path $projectRoot "backend\.venv\Scripts\python.exe"),
        (Join-Path $projectRoot "backend\.venv\bin\python"),
        "python",
        "python3"
    )
    foreach ($py in $pythonCandidates) {
        if (Test-Path -LiteralPath $py -PathType Leaf) {
            Write-BackupInfo "Running WAL checkpoint via Python (${py})"
            $escapedDbPath = $DbPath -replace "\\", "\\"
            $pyScript = @"
import sqlite3, sys
conn = sqlite3.connect(r'${escapedDbPath}')
try:
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    print('WAL checkpoint TRUNCATE OK')
except Exception:
    conn.execute('PRAGMA wal_checkpoint(PASSIVE)')
    print('WAL checkpoint PASSIVE OK')
finally:
    conn.close()
"@
            $result = & $py -c $pyScript 2>&1
            Write-BackupInfo "Python checkpoint: ${result}"
            return
        }
    }

    Write-BackupWarn "No sqlite3 CLI or Python venv found - skipping WAL checkpoint."
}

function Copy-DbFile {
    param(
        [string]$Source,
        [string]$Dest,
        [string]$Description
    )
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        Write-BackupInfo "${Description}: file not present, skipping."
        return $false
    }
    $size = (Get-Item -LiteralPath $Source).Length
    if ($size -eq 0) {
        Write-BackupInfo "${Description}: file is empty (0 bytes), skipping."
        return $false
    }
    if ($DryRun) {
        Write-BackupInfo "[DRYRUN] Would copy: ${Source} -> ${Dest} (${size} bytes)"
        return $true
    }
    Copy-Item -LiteralPath $Source -Destination $Dest -Force
    Write-BackupInfo "${Description}: copied (${size} bytes)"
    return $true
}

function Get-FileHashHex {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $hash = Get-FileHash -LiteralPath $Path -Algorithm SHA256
    return $hash.Hash.ToLowerInvariant()
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

Write-BackupInfo "=== SteamAnalysis DB Backup ==="
Write-BackupInfo "Source database : ${DatabasePath}"
Write-BackupInfo "Backup directory: ${BackupDir}"
Write-BackupInfo "Retention days  : ${RetentionDays}"
Write-BackupInfo "Dry run         : ${DryRun}"

# Resolve to absolute paths
$DatabasePath = [System.IO.Path]::GetFullPath($DatabasePath)
$BackupDir    = [System.IO.Path]::GetFullPath($BackupDir)

# Derive file names
$dbFileName    = [System.IO.Path]::GetFileName($DatabasePath)
$dbBaseName    = [System.IO.Path]::GetFileNameWithoutExtension($dbFileName)
$timestamp     = Get-UtcTimestamp
$backupPrefix  = "${dbBaseName}_${timestamp}.backup"

# WAL / SHM paths next to the source DB
$walPath = "${DatabasePath}-wal"
$shmPath = "${DatabasePath}-shm"

# --- Dry-run header ---
if ($DryRun) {
    Write-Host ""
    Write-Host "========== DRY-RUN MODE -- no changes will be made ==========" -ForegroundColor Cyan
    Write-Host ""
}

# --- 1. Create backup directory ---
if (-not $DryRun) {
    if (-not (Test-Path -LiteralPath $BackupDir -PathType Container)) {
        Write-BackupInfo "Creating backup directory: ${BackupDir}"
        New-Item -Path $BackupDir -ItemType Directory -Force | Out-Null
    }
} else {
    if (-not (Test-Path -LiteralPath $BackupDir -PathType Container)) {
        Write-BackupInfo "[DRYRUN] Would create directory: ${BackupDir}"
    }
}

# --- 2. WAL checkpoint ---
if (-not $NoCheckpoint) {
    if (-not $DryRun) {
        Invoke-WalCheckpoint -DbPath $DatabasePath
    } else {
        Write-BackupInfo "[DRYRUN] Would run WAL checkpoint on ${DatabasePath}"
    }
} else {
    Write-BackupWarn "WAL checkpoint skipped (-NoCheckpoint). Backup captures current on-disk state."
}

# --- 3. Copy database files ---
$mainDest = Join-Path $BackupDir "${backupPrefix}.sqlite3"
$walDest  = Join-Path $BackupDir "${backupPrefix}.sqlite3-wal"
$shmDest  = Join-Path $BackupDir "${backupPrefix}.sqlite3-shm"

$copiedFiles = @()

$wc = Copy-DbFile -Source $DatabasePath -Dest $mainDest -Description "Main DB"
if ($wc) { $copiedFiles += @{ Key = "Main"; Dst = $mainDest } }

$wc = Copy-DbFile -Source $walPath -Dest $walDest -Description "WAL file"
if ($wc) { $copiedFiles += @{ Key = "Wal"; Dst = $walDest } }

$wc = Copy-DbFile -Source $shmPath -Dest $shmDest -Description "SHM file"
if ($wc) { $copiedFiles += @{ Key = "Shm"; Dst = $shmDest } }

if ($copiedFiles.Count -eq 0) {
    Write-BackupError "No files were copied - backup ABORTED."
    exit 3
}

# --- 4. Generate manifest ---
$manifestPath = Join-Path $BackupDir "${backupPrefix}.manifest.json"
$manifestFiles = @()

foreach ($f in $copiedFiles) {
    $hash = if (-not $DryRun) { Get-FileHashHex -Path $f.Dst } else { "(dry-run)" }
    $size = if (-not $DryRun) { (Get-Item -LiteralPath $f.Dst).Length } else { 0 }
    $manifestFiles += @{
        label      = $f.Key
        filename   = Split-Path -Leaf $f.Dst
        size_bytes = $size
        sha256     = $hash
    }
}

$manifest = [ordered]@{
    backup_timestamp_utc = $timestamp
    source_database_path = $DatabasePath
    hostname             = $env:COMPUTERNAME
    script_version       = "1.0.0"
    wal_checkpoint       = (-not $NoCheckpoint)
    files                = $manifestFiles
}

if (-not $DryRun) {
    $manifestJson = $manifest | ConvertTo-Json -Depth 4
    Set-Content -LiteralPath $manifestPath -Value $manifestJson -Encoding UTF8
    Write-BackupInfo "Manifest written: ${manifestPath}"
} else {
    Write-BackupInfo "[DRYRUN] Would write manifest: ${manifestPath}"
    Write-BackupInfo "[DRYRUN] Manifest content:"
    ($manifest | ConvertTo-Json -Depth 4) -split "`n" | ForEach-Object { Write-Host "  ${_}" }
}

# --- 5. Clean up old backups ---
if ((-not $NoRetention) -and (-not $DryRun)) {
    Write-BackupInfo "Cleaning backups older than ${RetentionDays} day(s)"
    $cutoff = (Get-Date).ToUniversalTime().AddDays(-$RetentionDays)
    $pattern = "${dbBaseName}_*.backup.*"
    $oldFiles = Get-ChildItem -LiteralPath $BackupDir -Filter $pattern -File `
        | Where-Object { $_.LastWriteTimeUtc -lt $cutoff }

    if ($oldFiles) {
        foreach ($of in $oldFiles) {
            Write-BackupInfo "Removing old backup: $($of.Name)"
            Remove-Item -LiteralPath $of.FullName -Force -ErrorAction Continue
        }
        Write-BackupInfo "Removed $($oldFiles.Count) old backup file(s)."
    } else {
        Write-BackupInfo "No old backups to remove."
    }
} elseif ($DryRun) {
    Write-BackupInfo "[DRYRUN] Would remove backup files older than ${RetentionDays} day(s)."
    $cutoff = (Get-Date).ToUniversalTime().AddDays(-$RetentionDays)
    $pattern = "${dbBaseName}_*.backup.*"
    $oldFiles = Get-ChildItem -LiteralPath $BackupDir -Filter $pattern -File -ErrorAction SilentlyContinue `
        | Where-Object { $_.LastWriteTimeUtc -lt $cutoff }
    if ($oldFiles) {
        foreach ($of in $oldFiles) {
            Write-BackupInfo "[DRYRUN] Would remove: $($of.Name)"
        }
    } else {
        Write-BackupInfo "[DRYRUN] No old backups to remove."
    }
} else {
    Write-BackupInfo "Retention cleanup skipped (-NoRetention)."
}

# --- 6. Report ---
Write-Host ""
Write-Host "========== Backup completed ==========" -ForegroundColor Green
Write-Host "Timestamp  : ${timestamp}"
Write-Host "Backup dir : ${BackupDir}"
Write-Host "Files      :"
foreach ($f in $copiedFiles) {
    Write-Host "  $($f.Dst)"
}
Write-Host "Manifest   : ${manifestPath}"
Write-Host ""
exit 0
