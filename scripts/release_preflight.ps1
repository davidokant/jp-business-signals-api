[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

function Invoke-CheckedCommand {
    param([string]$FilePath, [string[]]$Arguments)

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $FilePath $($Arguments -join ' ')"
    }
}

Invoke-CheckedCommand "uv" @("run", "ruff", "check", ".")
Invoke-CheckedCommand "uv" @("run", "pytest", "-q")
Invoke-CheckedCommand "uv" @("build")

$blockedPaths = @(git ls-files .env data/production.db | Where-Object { $_ })
if ($blockedPaths) {
    throw "A secret or production database is already tracked by Git. Resolve before publishing."
}

Write-Host "Release preflight passed."
