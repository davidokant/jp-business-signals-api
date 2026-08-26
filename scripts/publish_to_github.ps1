[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern("^(https://github\.com/|git@github\.com:).+")]
    [string]$RepositoryUrl,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$AuthorName,

    [Parameter(Mandatory)]
    [ValidatePattern("^[^@\s]+@[^@\s]+\.[^@\s]+$")]
    [string]$AuthorEmail
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

& "$PSScriptRoot\release_preflight.ps1"
if ($LASTEXITCODE -ne 0) {
    throw "Release preflight failed. Nothing was staged or pushed."
}

git config user.name $AuthorName
git config user.email $AuthorEmail

$existingRemote = git remote get-url origin 2>$null
if ($LASTEXITCODE -eq 0 -and $existingRemote -ne $RepositoryUrl) {
    throw "An origin remote already exists and does not match the requested repository URL."
}
if ($LASTEXITCODE -ne 0) {
    git remote add origin $RepositoryUrl
}

git add --all
$stagedFiles = git diff --cached --name-only
if ($stagedFiles | Where-Object { $_ -match "(^|/)\.env$|(^|/)production\.db$" }) {
    git restore --staged -- .
    throw "A secret or production database was staged. The staging area was cleared."
}

if ($stagedFiles) {
    git commit -m "Initial JP Signals API MVP"
}

git branch -M main
git push --set-upstream origin main
Write-Host "Published to GitHub. You can now connect this repository in Railway."
