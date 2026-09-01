[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$version = "5.47.1"
$assetName = "railway-v$version-x86_64-pc-windows-msvc.zip"
$assetUrl = "https://github.com/railwayapp/cli/releases/download/v$version/$assetName"
$expectedHash = "0aece19acc63447f6e8a9f5a743522524daafee8ce5a6001c4361ea291babcb0"
$targetDir = Join-Path $env:LOCALAPPDATA "Railway\bin"
$targetBinary = Join-Path $targetDir "railway.exe"
$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$installTemp = [IO.Path]::GetFullPath(
    (Join-Path $tempBase ("railway-install-" + [guid]::NewGuid().ToString("N")))
)

New-Item -ItemType Directory -Path $installTemp | Out-Null

try {
    $archivePath = Join-Path $installTemp $assetName
    $extractPath = Join-Path $installTemp "extracted"

    Write-Host "Downloading Railway CLI v$version from the official GitHub release..." -ForegroundColor Cyan
    Invoke-WebRequest `
        -Uri $assetUrl `
        -OutFile $archivePath `
        -Headers @{ "User-Agent" = "Railway-CLI-Installer" }

    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "Railway CLI checksum mismatch. Nothing was installed."
    }

    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractPath
    $sourceBinary = Get-ChildItem `
        -LiteralPath $extractPath `
        -Filter "railway.exe" `
        -File `
        -Recurse | Select-Object -First 1
    if (-not $sourceBinary) {
        throw "railway.exe was not found in the verified archive."
    }

    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    Copy-Item -LiteralPath $sourceBinary.FullName -Destination $targetBinary -Force

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $pathEntries = @($userPath -split ";" | Where-Object { $_ })
    if ($pathEntries -notcontains $targetDir) {
        [Environment]::SetEnvironmentVariable(
            "Path",
            (($pathEntries + $targetDir) -join ";"),
            "User"
        )
    }

    & $targetBinary --version
    if ($LASTEXITCODE -ne 0) {
        throw "The installed Railway CLI did not start successfully."
    }

    Write-Host "SHA256 verified: $actualHash" -ForegroundColor Green
    Write-Host "Installed: $targetBinary" -ForegroundColor Green
}
finally {
    $resolvedTemp = [IO.Path]::GetFullPath($installTemp)
    if (
        $resolvedTemp.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $resolvedTemp)
    ) {
        Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
    }
}
