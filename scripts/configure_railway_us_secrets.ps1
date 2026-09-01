[CmdletBinding()]
param(
    [switch]$StdinSelfTest
)

$ErrorActionPreference = "Stop"

$railwayExe = Join-Path $env:LOCALAPPDATA "Railway\bin\railway.exe"
$projectName = "resourceful-recreation"
$environmentName = "production"
$serviceName = "us-federal-signals"

if (-not (Test-Path -LiteralPath $railwayExe)) {
    throw "Railway CLI was not found at the expected user installation path."
}

$projectsRaw = & $railwayExe list --json
$projectsParsed = ($projectsRaw -join [Environment]::NewLine) | ConvertFrom-Json
$projects = @()
foreach ($project in $projectsParsed) {
    $projects += $project
}
$targets = @($projects | Where-Object { $_.name -eq $projectName })
if ($targets.Count -ne 1) {
    throw "Expected exactly one target Railway project."
}

$target = $targets[0]
$projectId = @($target.id)[0]
$workspaceName = @($target.workspace.name)[0]
$serviceNames = @($target.services.edges | ForEach-Object { $_.node.name })
if ($serviceNames -notcontains $serviceName) {
    throw "The target US service was not found."
}
if ($serviceNames -notcontains "jp-business-signals-api") {
    throw "The expected Japan service boundary changed; refusing secret writes."
}

$linkArguments = @(
    "link",
    "-w",
    $workspaceName,
    "-p",
    $projectId,
    "-e",
    $environmentName,
    "-s",
    $serviceName,
    "--json"
)
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $linkOutput = & $railwayExe @linkArguments 2>&1
    $linkExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($linkExitCode -ne 0) {
    throw "The local Railway link could not be set to the US service."
}

function Assert-UsServiceLinked {
    $servicesRaw = & $railwayExe service list --json
    $servicesParsed = ($servicesRaw -join [Environment]::NewLine) | ConvertFrom-Json
    $linkedServices = @()
    foreach ($service in $servicesParsed) {
        $linkedServices += $service
    }
    $activeLinks = @()
    foreach ($service in $linkedServices) {
        if ($service.isLinked) {
            $activeLinks += $service
        }
    }
    if ($activeLinks.Count -ne 1 -or $activeLinks[0].name -ne $serviceName) {
        throw "The current Railway link is not the isolated US service."
    }
}

Assert-UsServiceLinked

function Invoke-RailwayVariableStdin {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$PlainValue
    )

    if ($Name -notmatch "^[A-Z0-9_]+$") {
        throw "The Railway variable name contains unsupported characters."
    }

    Assert-UsServiceLinked
    $setOutput = $PlainValue | & $railwayExe variable set `
        $Name `
        --stdin `
        --skip-deploys `
        --json 2>&1
    if ($LASTEXITCODE -ne 0) {
        if ($StdinSelfTest) {
            throw "Railway non-secret self-test failed: $setOutput"
        }
        throw "Railway rejected $Name without storing its value."
    }
    $setOutput = $null
}

function Set-RailwaySecret {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [Security.SecureString]$SecureValue
    )

    $bstr = [IntPtr]::Zero
    $plainValue = $null
    try {
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
        $plainValue = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        Invoke-RailwayVariableStdin -Name $Name -PlainValue $plainValue
        Write-Host "$Name submitted securely." -ForegroundColor Green
    }
    finally {
        $plainValue = $null
        if ($bstr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    }
}

if ($StdinSelfTest) {
    Invoke-RailwayVariableStdin -Name "US_RATE_LIMIT_PER_MINUTE" -PlainValue "10"
    Write-Host "WINDOWS_POWERSHELL_STDIN_SELF_TEST=PASS" -ForegroundColor Green
    exit 0
}

Write-Host "Target: $projectName / $environmentName / $serviceName" -ForegroundColor Cyan
Write-Host "Input is masked. Do not paste either value at a normal PowerShell prompt." -ForegroundColor Cyan

$samKey = Read-Host -Prompt "Paste SAM_API_KEY" -AsSecureString
$customerKey = Read-Host -Prompt "Paste a new random US_APP_API_KEYS value (32+ characters)" -AsSecureString

try {
    if ($samKey.Length -lt 16) {
        throw "SAM_API_KEY is shorter than the safety minimum."
    }
    if ($customerKey.Length -lt 32) {
        throw "US_APP_API_KEYS must contain at least 32 characters."
    }

    Set-RailwaySecret -Name "SAM_API_KEY" -SecureValue $samKey
    Set-RailwaySecret -Name "US_APP_API_KEYS" -SecureValue $customerKey

    Assert-UsServiceLinked
    $verifyRaw = & $railwayExe variable list --json 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Secret variable verification failed."
    }

    $variables = $verifyRaw | ConvertFrom-Json
    $names = @($variables.PSObject.Properties.Name)
    $required = @("SAM_API_KEY", "US_APP_API_KEYS")
    $missing = @($required | Where-Object { $_ -notin $names })
    if ($missing.Count -ne 0) {
        throw "One or more secret variables are missing after submission."
    }

    Write-Host "RAILWAY_SECRET_CONFIGURATION=PASS" -ForegroundColor Green
    Write-Host "No deployment was triggered." -ForegroundColor Green
}
finally {
    if ($samKey) {
        $samKey.Dispose()
    }
    if ($customerKey) {
        $customerKey.Dispose()
    }
}
