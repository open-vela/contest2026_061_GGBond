$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$adb = "C:\Users\Lenovo\.vela\sdk\tools\adb\win\adb.exe"
$emulator = "C:\Users\Lenovo\.vela\sdk\emulator\windows-x86_64\emulator.exe"
$python = "D:\MinConda\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$dist = Join-Path $repoRoot "quickapp\WristSpace\dist"
$upper = Join-Path $repoRoot "pc\Aiot_PyCharm\main.py"
$package = "com.application.watch.demo"
$deviceName = "redmi_watch"
$appDir = "/data/quickapp/app"

function Test-HttpReady {
    try { Invoke-RestMethod -Uri "http://127.0.0.1:8787/health" -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}

function Get-Health {
    try { return Invoke-RestMethod -Uri "http://127.0.0.1:8787/health" -TimeoutSec 3 } catch { return $null }
}

function Get-AdbDevice {
    & $adb devices | Select-String "emulator-5554\s+device"
}

function Wait-ForDevice {
    param([int]$Seconds = 120)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Get-AdbDevice) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Wait-ForVelaServices {
    param([int]$Seconds = 45)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $psLines = & $adb -s emulator-5554 shell ps 2>$null
        $hasActivity = $psLines | Select-String "miwear_activity_service"
        $hasServiceManager = $psLines | Select-String "servicemanager"
        if ($hasActivity -and $hasServiceManager) {
            Start-Sleep -Seconds 5
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Wait-ForDeliveredSeq {
    param([int]$Seq, [int]$Seconds = 22)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $health = Get-Health
        if ($health -and $health.lastDelivered -and [int]$health.lastDelivered.seq -ge $Seq) { return $health }
        Start-Sleep -Milliseconds 700
    }
    return Get-Health
}

function Stop-HostVappShells {
    try {
        Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $_.CommandLine -match 'adb(\.exe)?.*vapp app/com\.application\.watch\.demo'
        } | ForEach-Object {
            Write-Host "Stop stale host adb vapp process: $($_.ProcessId)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    } catch {
        Write-Host "Skip stale host vapp scan: no permission for Win32_Process."
    }
}

function Stop-DeviceVapp {
    Write-Host "Stop stale device vapp/app processes if present..."
    $pidText = (& $adb -s emulator-5554 shell "pidof $package" 2>$null) -join " "
    $pids = @(
        $pidText -split '\s+' |
            Where-Object { $_ -match '^\d+$' } |
            ForEach-Object { [int]$_ }
    )
    foreach ($pid in ($pids | Select-Object -Unique)) {
        Write-Host "Kill stale app/vapp pid $pid"
        & $adb -s emulator-5554 shell "kill $pid" | Out-Null
    }
    for ($i = 0; $i -lt 10; $i++) {
        $remaining = (& $adb -s emulator-5554 shell "pidof $package" 2>$null) -join " "
        if (-not ($remaining -match '\d')) {
            break
        }
        Start-Sleep -Milliseconds 300
    }
    if ((& $adb -s emulator-5554 shell "pidof $package" 2>$null) -match '\d') {
        throw "Stale app process did not exit: $package"
    }
    Start-Sleep -Seconds 1
}

function Start-VappJob {
    param([string]$Reason)
    Write-Host "Start wrist-control app by vapp ($Reason)..."
    return Start-Process -FilePath $adb -WindowStyle Hidden -PassThru -ArgumentList @(
        "-s",
        "emulator-5554",
        "shell",
        "vapp",
        "app/$package"
    )
}

$rpkItem = Get-ChildItem $dist -Filter "com.application.watch.demo.debug.*.rpk" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $rpkItem) { throw "No RPK found in $dist. Please run npm run build first." }
$rpk = $rpkItem.FullName

Write-Host "Rectangle mode: launch redmi_watch as a standalone rectangular watch."
Write-Host "Use npm run demo:rect for this mode; do not start AIoT IDE embedded preview at the same time."

if (-not (Test-HttpReady)) {
    if ($python -ne "python" -and -not (Test-Path $python)) {
        throw "Python runtime not found: $python"
    }
    Write-Host "PC service is not ready. Start upper computer with $python ..."
    Start-Process -FilePath $python -ArgumentList @($upper) -WorkingDirectory (Split-Path $upper) -WindowStyle Hidden
    for ($i = 0; $i -lt 12; $i++) {
        if (Test-HttpReady) { break }
        Start-Sleep -Seconds 1
    }
}

if (-not (Test-HttpReady)) {
    throw "PC service did not become ready at http://127.0.0.1:8787/health. Start $upper first, then retry."
}

Stop-HostVappShells
Get-Process -Name "emulator","qemu-system-armel" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3

& $adb kill-server | Out-Host
Start-Sleep -Seconds 1
& $adb start-server | Out-Host

Write-Host "Launch rectangular emulator: $deviceName"
Start-Process -FilePath $emulator -WindowStyle Normal -ArgumentList @(
    "-vela",
    "-avd",
    $deviceName,
    "-show-kernel",
    "-network-user-mode-options",
    "hostfwd=tcp:127.0.0.1:10055-10.0.2.15:101",
    "-qemu",
    "-device",
    "virtio-snd,bus=virtio-mmio-bus.2",
    "-allow-host-audio",
    "-semihosting"
)

if (-not (Wait-ForDevice -Seconds 120)) {
    throw "emulator-5554 not found for $deviceName. Close any embedded preview and run npm run demo:rect again."
}

Write-Host "Wait for Vela activity services..."
if (-not (Wait-ForVelaServices -Seconds 45)) {
    throw "Vela services did not become ready. Restart the rectangular emulator and try again."
}

Stop-DeviceVapp

Write-Host "Deploy clean quickapp with Vela pre-4 vapp path..."
& $adb -s emulator-5554 shell "rm -r $appDir/$package" | Out-Host
& $adb -s emulator-5554 shell "rm $appDir/$package.rpk" | Out-Host
& $adb -s emulator-5554 shell "mkdir $appDir" | Out-Host
& $adb -s emulator-5554 shell "mkdir $appDir/$package" | Out-Host
& $adb -s emulator-5554 push $rpk "$appDir/$package.rpk" | Out-Host
& $adb -s emulator-5554 shell "unzip -o $appDir/$package.rpk -d $appDir/$package" | Out-Host

$vappJob = Start-VappJob -Reason "first"
Start-Sleep -Seconds 8

$resetResult = Invoke-RestMethod -Uri "http://127.0.0.1:8787/aiot-command" -Method Post -ContentType "application/json; charset=utf-8" -Body '{"action":"reset_state","label":"rect_start_sync"}'
$resetSeq = [int]$resetResult.queued.seq
$health = Wait-ForDeliveredSeq -Seq $resetSeq -Seconds 35

$health | ConvertTo-Json -Depth 8 | Out-Host

if (-not $health -or -not $health.lastDelivered -or [int]$health.lastDelivered.seq -lt $resetSeq) {
    Write-Host "Single vapp instance did not consume commands. Recent device log:"
    & $adb -s emulator-5554 shell dmesg | Select-Object -Last 80 | Out-Host
    throw "The rectangular app did not consume commands. No second vapp instance was started."
}

Write-Host "Done: rectangular wrist-control app is running, visible, and polling PC commands."
