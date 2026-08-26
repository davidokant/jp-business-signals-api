param(
    [string]$EnvFile = (Join-Path $PSScriptRoot "..\.env")
)

$ErrorActionPreference = "Stop"
$resolvedEnvFile = [System.IO.Path]::GetFullPath($EnvFile)
$exampleFile = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.env.example"))

$secureToken = Read-Host "Paste the gBizINFO token (input is hidden)" -AsSecureString
$tokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPointer).Trim()
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPointer)
}

if ([string]::IsNullOrWhiteSpace($token)) {
    throw "The token is empty."
}
if ($token -match "\s") {
    throw "The token contains whitespace. Copy only the token value."
}

if (Test-Path -LiteralPath $resolvedEnvFile) {
    $lines = @(Get-Content -LiteralPath $resolvedEnvFile)
}
else {
    $lines = @(Get-Content -LiteralPath $exampleFile)
}

$replacement = "GBIZ_API_TOKEN=$token"
$found = $false
$updatedLines = @(
    foreach ($line in $lines) {
        if ($line -match "^\s*GBIZ_API_TOKEN\s*=") {
            $replacement
            $found = $true
        }
        else {
            $line
        }
    }
)
if (-not $found) {
    $updatedLines += $replacement
}

[System.IO.File]::WriteAllLines(
    $resolvedEnvFile,
    $updatedLines,
    [System.Text.UTF8Encoding]::new($false)
)

$savedLength = $token.Length
$token = $null
Write-Host "Saved a $savedLength-character token to $resolvedEnvFile"
Write-Host "The token value was not printed. Keep this file private."
