# SteamAnalysis CI check script
# Usage: .\scripts\check.ps1
# Runs: backend tests, evals, ruff, mypy, frontend typecheck, lint, build, fresh DB migration

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

$BackendDir = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$PythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"
$NpmExe = "npm.cmd"

$Failed = @()

function Write-Step {
    param([string]$Name)
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
}

function Run-Check {
    param(
        [string]$Name,
        [string]$WorkingDir,
        [string]$Command,
        [string]$Arguments
    )
    Write-Step $Name
    $proc = Start-Process -FilePath $Command -ArgumentList $Arguments -WorkingDirectory $WorkingDir -NoNewWindow -PassThru -Wait
    if ($proc.ExitCode -ne 0) {
        Write-Host "  FAILED (exit $($proc.ExitCode))" -ForegroundColor Red
        $global:Failed += $Name
    } else {
        Write-Host "  PASSED" -ForegroundColor Green
    }
}

# ── Backend ────────────────────────────────────────────────────────────
Write-Host "`n====== Backend Checks ======" -ForegroundColor Yellow

# 1. Backend tests
Run-Check -Name "backend-tests" -WorkingDir $BackendDir -Command $PythonExe -Arguments "-m pytest app/tests -q"

# 2. Backend evals
Run-Check -Name "backend-evals" -WorkingDir $BackendDir -Command $PythonExe -Arguments "-m pytest app/evals -q"

# 3. Ruff lint
Run-Check -Name "backend-ruff" -WorkingDir $BackendDir -Command $PythonExe -Arguments "-m ruff check app"

# 4. Mypy typecheck
Run-Check -Name "backend-mypy" -WorkingDir $BackendDir -Command $PythonExe -Arguments "-m mypy app"

# ── Frontend ───────────────────────────────────────────────────────────
Write-Host "`n====== Frontend Checks ======" -ForegroundColor Yellow

# 5. Frontend unit tests
Run-Check -Name "frontend-tests" -WorkingDir $FrontendDir -Command $NpmExe -Arguments "run test:unit -- --run"

# 6. Frontend typecheck
Run-Check -Name "frontend-typecheck" -WorkingDir $FrontendDir -Command $NpmExe -Arguments "run typecheck"

# 7. Frontend lint
Run-Check -Name "frontend-lint" -WorkingDir $FrontendDir -Command $NpmExe -Arguments "run lint"

# 8. Frontend build
Run-Check -Name "frontend-build" -WorkingDir $FrontendDir -Command $NpmExe -Arguments "run build"

# ── DB Migration ───────────────────────────────────────────────────────
Write-Host "`n====== DB Migration Smoke Test ======" -ForegroundColor Yellow
$tmpDb = Join-Path $env:TEMP "steamanalysis_alembic_fresh_test.sqlite3"
Remove-Item -LiteralPath $tmpDb -ErrorAction SilentlyContinue -Force
$env:STEAMANALYSIS_DATABASE_URL = "sqlite:///" + ($tmpDb -replace '\\', '/')

$migProc = Start-Process -FilePath $PythonExe -ArgumentList "-m alembic upgrade head" -WorkingDirectory $BackendDir -NoNewWindow -PassThru -Wait
if ($migProc.ExitCode -ne 0) {
    Write-Host "  DB Migration FAILED (exit $($migProc.ExitCode))" -ForegroundColor Red
    $Failed += "db-migration"
} else {
    Write-Host "  DB Migration PASSED" -ForegroundColor Green
}
Remove-Item -LiteralPath $tmpDb -ErrorAction SilentlyContinue -Force

# ── Summary ────────────────────────────────────────────────────────────
Write-Host "`n====== Summary ======" -ForegroundColor Yellow
if ($Failed.Count -eq 0) {
    Write-Host "All checks PASSED!" -ForegroundColor Green
    exit 0
} else {
    Write-Host "FAILED: $($Failed -join ', ')" -ForegroundColor Red
    exit 1
}
