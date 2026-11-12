# One-click deploy: package code and upload to server.
#
# Usage (run in local PowerShell):
#   .\deploy.ps1              # sync code only
#   .\deploy.ps1 -Build       # sync code + rebuild frontend on server
#
# Packages code only - no venv, deps, build output, or indexes.
# NOTE: keep this file ASCII-only. PowerShell 5.1 decodes BOM-less .ps1 as GBK,
#       so non-ASCII characters corrupt quoting and break parsing.

param(
    [switch]$Build
)

$ErrorActionPreference = "Stop"

$ROOT = "D:\rag_agent"
$SERVER = "admin@47.117.189.10"
$REMOTE = "~/group_3/xingshuai/rag_agent"
$PKG = Join-Path $env:TEMP "rag_deploy.tar.gz"

$INCLUDE = @("src", "frontend/src", "evals", "scripts", "pyproject.toml")
$EXCLUDE = @(
    ".venv", "node_modules", "dist", "data/index", "__pycache__",
    ".git", "evals/reports", "_export", ".env"
)

Write-Host "[1/3] Packaging..." -ForegroundColor Cyan
$excludeArgs = $EXCLUDE | ForEach-Object { "--exclude=$_" }
& tar -czf $PKG -C $ROOT @excludeArgs @INCLUDE

if (-not (Test-Path $PKG)) {
    Write-Host "ERROR: packaging failed" -ForegroundColor Red
    exit 1
}
$sizeMB = [math]::Round((Get-Item $PKG).Length / 1MB, 2)
Write-Host "      size: $sizeMB MB" -ForegroundColor Green

Write-Host "[2/3] Uploading (enter server password)..." -ForegroundColor Cyan
& scp $PKG "${SERVER}:${REMOTE}/"

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: upload failed - server files NOT updated" -ForegroundColor Red
    Write-Host "       check password, or wait 1-2 min if locked out" -ForegroundColor Yellow
    Remove-Item $PKG -Force -ErrorAction SilentlyContinue
    exit 1
}

Write-Host "[3/3] Upload OK. Run these ON THE SERVER:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  cd $REMOTE"
Write-Host "  tar -xzf rag_deploy.tar.gz && rm rag_deploy.tar.gz"
if ($Build) {
    Write-Host "  cd frontend && npm run build && cd .."
}
Write-Host "  sudo systemctl restart rag-agent-xingshuai"
Write-Host "  curl -s http://127.0.0.1:8000/api/health && echo"

Remove-Item $PKG -Force -ErrorAction SilentlyContinue
