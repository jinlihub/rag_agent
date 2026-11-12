# 切换本地开发环境的数据库配置
#   用法：.\use-db.ps1 school    → 连学校库 192.168.10.120（需在同网段）
#         .\use-db.ps1 tunnel    → 连服务器库（需先开 SSH 隧道）
#         .\use-db.ps1 status    → 查看当前用的是哪套

param(
    [Parameter(Position = 0)]
    [ValidateSet("school", "tunnel", "status")]
    [string]$Mode = "status"
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $root ".env"
$schoolFile = Join-Path $root ".env.school"
$tunnelFile = Join-Path $root ".env.tunnel"

function Get-CurrentHost_ {
    if (-not (Test-Path $envFile)) { return "(无 .env)" }
    $line = Select-String -Path $envFile -Pattern "^DB_HOST=" | Select-Object -First 1
    if ($line) { return ($line.Line -replace "^DB_HOST=", "") }
    return "(未设置)"
}

switch ($Mode) {
    "status" {
        $cur = Get-CurrentHost_
        Write-Host "当前 DB_HOST = $cur"
        if ($cur -eq "192.168.10.120") { Write-Host "→ 学校库模式（需在同一网段）" }
        elseif ($cur -eq "127.0.0.1") { Write-Host "→ 隧道模式（需先执行 ssh -L 3306:localhost:3306 -L 5432:localhost:5432 admin@47.117.189.10）" }
    }
    "school" {
        if (-not (Test-Path $schoolFile)) { Write-Error "缺少 .env.school"; exit 1 }
        Copy-Item $schoolFile $envFile -Force
        Write-Host "已切换到学校库（DB_HOST=192.168.10.120）"
    }
    "tunnel" {
        if (-not (Test-Path $tunnelFile)) { Write-Error "缺少 .env.tunnel"; exit 1 }
        Copy-Item $tunnelFile $envFile -Force
        Write-Host "已切换到隧道模式（DB_HOST=127.0.0.1）"
        Write-Host "记得先开隧道："
        Write-Host "  ssh -L 3306:localhost:3306 -L 5432:localhost:5432 admin@47.117.189.10"
    }
}
