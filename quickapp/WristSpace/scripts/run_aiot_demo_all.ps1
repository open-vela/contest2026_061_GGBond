$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = "D:\MinConda\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$upper = Join-Path $repoRoot "pc\Aiot_PyCharm\main.py"
$rect = Join-Path $PSScriptRoot "run_aiot_demo_rect.ps1"

function Test-HttpReady {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:8787/health" -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

if ($python -ne "python" -and -not (Test-Path $python)) {
    throw "Python runtime not found: $python"
}
if (-not (Test-Path $upper)) {
    throw "Upper computer entry file not found: $upper"
}
if (-not (Test-Path $rect)) {
    throw "Rectangle launcher not found: $rect"
}

Write-Host "One-command mode: PC upper computer + standalone rectangular AIoT."
if (Test-HttpReady) {
    Write-Host "Reuse existing PC service: http://127.0.0.1:8787"
} else {
    Write-Host "Start visible PC upper computer..."
    Start-Process -FilePath $python `
        -ArgumentList @($upper) `
        -WorkingDirectory (Split-Path $upper) `
        -WindowStyle Normal | Out-Null

    $ready = $false
    for ($i = 1; $i -le 20; $i++) {
        Start-Sleep -Seconds 1
        if (Test-HttpReady) {
            $ready = $true
            break
        }
        Write-Host "Waiting for PC service... $i/20"
    }
    if (-not $ready) {
        throw "PC service did not become ready at http://127.0.0.1:8787/health."
    }
}

& $rect
