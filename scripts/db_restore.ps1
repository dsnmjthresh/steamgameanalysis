# SteamAnalysis - SQLite database restore script (PowerShell)
# =============================================================================
# Restores a SQLite database from a backup set produced by db_backup.ps1.
# By default the script REFUSES to overwrite an existing file at the target
# path.  Use -Force to override.
#
# Usage:
#   .\scripts\db_restore.ps1 -BackupFile .\backups\steamanalysis_20260609T120000Z.backup.sqlite3 -TargetPath .\restored.sqlite3
#   .\scripts\db_restore.ps1 -BackupFile .\backups\...backup.sqlite3 -TargetPath .\restored.sqlite3 -Force
#   .\scripts\db_restore.ps1 -BackupFile .\backups\...backup.sqlite3 -TargetPath .\restored.sqlite3 -DryRun
#
# Exit codes: 0 = success, 1 = usage / argument error, 2 = backup not found,
#             3 = target exists and was refused, 4 = integrity check failed,
#             5 = restore failure.
# =============================================================================

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, HelpMessage = "Path to the backed-up .sqlite3 file")]
    [ValidateScript({
        if (-not (Test-Path -LiteralPath $_ -PathType Leaf)) {
            throw "Backup file not found: $_"
        }
        $true
    })]
    [string]$BackupFile,

    [Parameter(Mandatory = $true, HelpMessage = "Target path for the restored database")]
    [string]$TargetPath,

    [Parameter(HelpMessage = "Overwrite existing target without prompting")]
    [switch]$Force,

    [Parameter(HelpMessage = "Show actions without executing")]
    [switch]$DryRun,

    [Parameter(HelpMessage = "Skip post-restore integrity check")]
    [switch]$SkipIntegrity
)

$ErrorActionPreference = "Continue"
$ScriptName = [System.IO.Path]::GetFileName($MyInvocation.MyCommand.Path)
# Capture script root at top level — $MyInvocation is unreliable inside functions
$ScriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

function Write-RestoreInfo {
    param([string]$Message)
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [INFO ] ${Message}"
}

function Write-RestoreWarn {
    param([string]$Message)
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [WARN ] ${Message}" -ForegroundColor Yellow
}

function Write-RestoreError {
    param([string]$Message)
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [ERROR] ${Message}" -ForegroundColor Red
}

function Find-CompanionFiles {
    param([string]$MainFile)
    $dir      = Split-Path -Parent $MainFile
    $baseName = Split-Path -Leaf $MainFile
    $prefix   = $baseName -replace '\.sqlite3$', ''

    return @{
        Wal      = if ($prefix) { Join-Path $dir "${prefix}.sqlite3-wal" }   else { $null }
        Shm      = if ($prefix) { Join-Path $dir "${prefix}.sqlite3-shm" }   else { $null }
        Manifest = if ($prefix) { Join-Path $dir "${prefix}.manifest.json" } else { $null }
    }
}

function Test-TargetConflict {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }

    $size = (Get-Item -LiteralPath $Path).Length
    Write-RestoreWarn "Target file already exists: ${Path} (${size} bytes)"

    if ($Force) {
        Write-RestoreInfo "-Force specified - will overwrite."
        return $false
    }

    $response = Read-Host "Overwrite existing file? [y/N]"
    if ($response -notmatch '^[Yy]$') {
        Write-RestoreError "Restore ABORTED by user - target exists and overwrite was denied."
        return $true
    }
    Write-RestoreInfo "User confirmed overwrite."
    return $false
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

function Invoke-IntegrityCheck {
    param([string]$DbPath)

    $sqliteCli = Get-Sqlite3Cli
    if ($sqliteCli) {
        Write-RestoreInfo "Running integrity_check via sqlite3 CLI"
        $result = & $sqliteCli $DbPath "PRAGMA integrity_check;" 2>&1
        if ($LASTEXITCODE -ne 0 -or $result -notmatch '^\s*ok\s*$') {
            Write-RestoreError "Integrity check FAILED: ${result}"
            return $false
        }
        Write-RestoreInfo "Integrity check PASSED: ${result}"
        return $true
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
            Write-RestoreInfo "Running integrity_check via Python (${py})"
            $escapedDbPath = $DbPath -replace "\\", "\\"
            $pyScript = @"
import sqlite3, sys
conn = sqlite3.connect(r'${escapedDbPath}')
try:
    row = conn.execute('PRAGMA integrity_check').fetchone()
    if row and row[0] == 'ok':
        print('ok')
    else:
        msg = str(row[0]) if row else 'no result'
        print(f'FAILED: {msg}', file=sys.stderr)
        sys.exit(1)
finally:
    conn.close()
"@
            $result = & $py -c $pyScript 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-RestoreInfo "Integrity check PASSED"
                return $true
            }
            Write-RestoreError "Integrity check FAILED: ${result}"
            return $false
        }
    }

    Write-RestoreWarn "No sqlite3 CLI or Python venv found - skipping integrity check."
    return $true
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

Write-RestoreInfo "=== SteamAnalysis DB Restore ==="
Write-RestoreInfo "Backup file : ${BackupFile}"
Write-RestoreInfo "Target path : ${TargetPath}"
Write-RestoreInfo "Force       : ${Force}"
Write-RestoreInfo "Dry run     : ${DryRun}"

# Resolve absolute paths
$BackupFile = [System.IO.Path]::GetFullPath($BackupFile)
$TargetPath = [System.IO.Path]::GetFullPath($TargetPath)
$TargetDir  = Split-Path -Parent $TargetPath

Write-RestoreInfo "Target dir  : ${TargetDir}"

# --- Dry-run header ---
if ($DryRun) {
    Write-Host ""
    Write-Host "========== DRY-RUN MODE -- no changes will be made ==========" -ForegroundColor Cyan
    Write-Host ""
}

# --- 1. Locate companion files ---
$companions = Find-CompanionFiles -MainFile $BackupFile
Write-RestoreInfo "Companion files:"
$walExists = Test-Path -LiteralPath $companions.Wal -PathType Leaf
$shmExists = Test-Path -LiteralPath $companions.Shm -PathType Leaf
$manifestExists = Test-Path -LiteralPath $companions.Manifest -PathType Leaf
Write-RestoreInfo "  WAL     : $($companions.Wal)  $(if ($walExists) {'(exists)'} else {'(not found)'})"
Write-RestoreInfo "  SHM     : $($companions.Shm)  $(if ($shmExists) {'(exists)'} else {'(not found)'})"
Write-RestoreInfo "  Manifest: $($companions.Manifest)  $(if ($manifestExists) {'(exists)'} else {'(not found)'})"

# --- 2. Display manifest if available ---
if ($manifestExists) {
    try {
        $manifestContent = Get-Content -LiteralPath $companions.Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-RestoreInfo "Backup timestamp (from manifest): $($manifestContent.backup_timestamp_utc)"
        Write-RestoreInfo "Source database (from manifest):   $($manifestContent.source_database_path)"
        Write-RestoreInfo "Backup host (from manifest):       $($manifestContent.hostname)"
    } catch {
        Write-RestoreWarn "Could not parse manifest file."
    }
}

# --- 3. Pre-flight: target conflict check ---
if (-not $DryRun) {
    $conflict = Test-TargetConflict -Path $TargetPath
    if ($conflict) {
        exit 3
    }
} else {
    if (Test-Path -LiteralPath $TargetPath -PathType Leaf) {
        Write-RestoreInfo "[DRYRUN] Target exists - would prompt for overwrite (or honour -Force)."
    }
}

# --- 4. Create target directory if needed ---
if (-not $DryRun) {
    if (-not (Test-Path -LiteralPath $TargetDir -PathType Container)) {
        Write-RestoreInfo "Creating target directory: ${TargetDir}"
        New-Item -Path $TargetDir -ItemType Directory -Force | Out-Null
    }
} else {
    if (-not (Test-Path -LiteralPath $TargetDir -PathType Container)) {
        Write-RestoreInfo "[DRYRUN] Would create target directory: ${TargetDir}"
    }
}

# --- 5. Copy restored files ---
$restoredFiles = @()

function Restore-File {
    param([string]$Src, [string]$Dst, [string]$Label)
    if (-not (Test-Path -LiteralPath $Src -PathType Leaf)) {
        Write-RestoreInfo "${Label}: source not present, skipping."
        return
    }
    if ($DryRun) {
        $srcSize = (Get-Item -LiteralPath $Src).Length
        Write-RestoreInfo "[DRYRUN] Would copy: ${Src} -> ${Dst} (${srcSize} bytes)"
        $script:restoredFiles += @{ Label = $Label; Dst = $Dst }
        return
    }
    Copy-Item -LiteralPath $Src -Destination $Dst -Force
    $dstSize = (Get-Item -LiteralPath $Dst).Length
    Write-RestoreInfo "${Label}: restored (${dstSize} bytes)"
    $script:restoredFiles += @{ Label = $Label; Dst = $Dst }
}

# Restore main DB
Restore-File -Src $BackupFile -Dst $TargetPath -Label "Main DB"

# Restore WAL / SHM only if they exist alongside the backup
$targetWal = "${TargetPath}-wal"
$targetShm = "${TargetPath}-shm"
Restore-File -Src $companions.Wal -Dst $targetWal -Label "WAL file"
Restore-File -Src $companions.Shm -Dst $targetShm -Label "SHM file"

if ($restoredFiles.Count -eq 0) {
    Write-RestoreError "No files were restored - ABORTED."
    exit 5
}

# --- 6. Display checksums ---
Write-RestoreInfo "Checksums (SHA256):"
foreach ($f in $restoredFiles) {
    if (-not $DryRun) {
        $hash = Get-FileHash -LiteralPath $f.Dst -Algorithm SHA256
        Write-RestoreInfo "  $($f.Label): $($hash.Hash.ToLowerInvariant())"
    } else {
        Write-RestoreInfo "  $($f.Label): (dry-run)"
    }
}

# --- 7. Integrity check ---
if (-not $SkipIntegrity) {
    if (-not $DryRun) {
        Write-Host ""
        $ok = Invoke-IntegrityCheck -DbPath $TargetPath
        if (-not $ok) {
            Write-RestoreError "Post-restore integrity check FAILED."
            Write-RestoreError "The restored database may be corrupt."
            Write-RestoreError "Delete ${TargetPath} and retry with a different backup."
            exit 4
        }
    } else {
        Write-RestoreInfo "[DRYRUN] Would run PRAGMA integrity_check on restored database."
    }
} else {
    Write-RestoreWarn "Integrity check skipped (-SkipIntegrity)."
}

# --- 8. Checkpoint restored WAL into main DB ---
if ((-not $DryRun) -and (Test-Path -LiteralPath $targetWal -PathType Leaf)) {
    Write-RestoreInfo "Restored DB has WAL file - running checkpoint to merge"
    $sqliteCli = Get-Sqlite3Cli
    if ($sqliteCli) {
        $null = & $sqliteCli $TargetPath "PRAGMA wal_checkpoint(TRUNCATE);" 2>&1
        Write-RestoreInfo "WAL checkpointed into restored DB."
        # Clean up WAL/SHM if now zero-length
        if ((Get-Item -LiteralPath $targetWal).Length -eq 0) {
            Remove-Item -LiteralPath $targetWal -Force
            Write-RestoreInfo "Removed zero-length restored WAL file."
        }
        if (Test-Path -LiteralPath $targetShm -PathType Leaf) {
            Remove-Item -LiteralPath $targetShm -Force
            Write-RestoreInfo "Removed restored SHM file."
        }
    }
}

# --- 9. Report ---
Write-Host ""
Write-Host "========== Restore completed ==========" -ForegroundColor Green
Write-Host "Target       : ${TargetPath}"
Write-Host "Files restored:"
foreach ($f in $restoredFiles) {
    Write-Host "  $($f.Label): $($f.Dst)"
}

# --- 10. Usage hint ---
$urlPath = $TargetPath -replace '\\', '/'
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  Set environment variable:"
Write-Host "    `$env:STEAMANALYSIS_DATABASE_URL = 'sqlite:///${urlPath}'"
Write-Host "  Or update your .env file:"
Write-Host "    STEAMANALYSIS_DATABASE_URL=sqlite:///${urlPath}"
Write-Host ""
exit 0
