$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$adb = "C:\Users\Lenovo\.vela\sdk\tools\adb\win\adb.exe"
$emulator = "C:\Users\Lenovo\.vela\sdk\emulator\windows-x86_64\emulator.exe"
$dist = Join-Path $repoRoot "quickapp\WristSpace\dist"
$rpk = (Get-ChildItem $dist -Filter "com.application.watch.demo.debug.*.rpk" | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
$upper = Join-Path $repoRoot "pc\Aiot_PyCharm\main.py"
$package = "com.application.watch.demo"

if (-not $rpk) {
    throw "No RPK found in $dist. Please run npm run build first."
}

function Test-HttpReady {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:8787/health" -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Get-AdbDevices {
    & $adb devices | Select-String "emulator-5554\s+device"
}

function Get-Health {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:8787/health" -TimeoutSec 3
    } catch {
        return $null
    }
}

function Wait-ForPolling {
    param([int]$Seconds = 3)

    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $health = Get-Health
        if ($health -and $health.lastPollAt -ne 0) {
            return $health
        }
        Start-Sleep -Milliseconds 500
    }
    return Get-Health
}

Write-Host "1/5 Start PC bridge..."
if (-not (Test-HttpReady)) {
    Start-Process -FilePath "python" -ArgumentList @($upper) -WorkingDirectory (Split-Path $upper)
    Start-Sleep -Seconds 2
}

Write-Host "2/5 Check Vela emulator..."
if (-not (Get-AdbDevices)) {
    Start-Process -FilePath $emulator -ArgumentList @(
        "-vela",
        "-avd",
        "Vela_Virtual_Device",
        "-show-kernel",
        "-network-user-mode-options",
        "hostfwd=tcp:127.0.0.1:10055-10.0.2.15:101",
        "-qemu",
        "-device",
        "virtio-snd,bus=virtio-mmio-bus.2",
        "-allow-host-audio",
        "-semihosting"
    )
}

Write-Host "3/5 Wait for adb..."
for ($i = 0; $i -lt 40; $i++) {
    if (Get-AdbDevices) {
        break
    }
    Start-Sleep -Seconds 2
}

if (-not (Get-AdbDevices)) {
    throw "emulator-5554 not found. Please make sure Vela_Virtual_Device is running."
}

Write-Host "4/5 Install and start wrist-control app..."
Write-Host "Stop and uninstall old app to clear quickapp cache..."
& $adb -s emulator-5554 shell am stop $package | Out-Host
& $adb -s emulator-5554 shell pm uninstall $package | Out-Host
& $adb -s emulator-5554 push $rpk /data/app/$package.rpk | Out-Host
& $adb -s emulator-5554 shell pm install /data/app/$package.rpk | Out-Host

Write-Host "5/5 Check polling state..."
$health = $null
for ($i = 1; $i -le 8; $i++) {
    Write-Host "am start attempt $i/8"
    & $adb -s emulator-5554 shell am start $package | Out-Host
    $health = Wait-ForPolling -Seconds 4
    if ($health -and $health.lastPollAt -ne 0) {
        break
    }
    Start-Sleep -Seconds 1
}

if (-not $health) {
    $health = Get-Health
}

$health | ConvertTo-Json -Depth 6 | Out-Host

if (-not $health -or $health.lastPollAt -eq 0) {
    Write-Host "Start command was sent, but the app is not polling yet. Click Debug in IDE once, or run this script again."
} else {
    Write-Host "Sync PC and watch initial state..."
    Invoke-RestMethod -Uri "http://127.0.0.1:8787/aiot-command" -Method Post -ContentType "application/json; charset=utf-8" -Body '{"action":"reset_state"}' | Out-Null
    Start-Sleep -Seconds 2
    Write-Host "Done: wrist-control app is running. PC bridge buttons can control the AIoT page."
}
