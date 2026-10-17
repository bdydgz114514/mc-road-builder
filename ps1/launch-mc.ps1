# Launch Minecraft, wait for the bridge, and if the game is sitting in the main menu,
# click through: multiplayer -> double-click the server list entry -> wait for the world.
$ErrorActionPreference = 'Continue'
$dir = 'D:\mc-road-builder'

Write-Output '=== kill any running instance ==='
Get-CimInstance Win32_Process -Filter "Name='java.exe'" |
    Where-Object { $_.CommandLine -like '*KnotClient*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 8

Write-Output '=== launch ==='
& powershell -NoProfile -ExecutionPolicy Bypass -File "$dir\ensure-mc.ps1" | Select-Object -Last 1

Write-Output '=== wait for the world ==='
$inWorld = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 5
    try {
        $r = Invoke-RestMethod 'http://127.0.0.1:25580/state' -TimeoutSec 4 -ErrorAction Stop
        if ($r.ok) { $inWorld = $true; break }
    } catch { }
}
if ($inWorld) { Write-Output "in world after $($i*5)s"; exit 0 }

Write-Output '=== still in menu: click multiplayer, then the server entry ==='
Start-Sleep -Seconds 15
& powershell -NoProfile -ExecutionPolicy Bypass -File "$dir\click.ps1" -X 1279 -Y 616 -WaitMs 2500 | Out-Null
& powershell -NoProfile -ExecutionPolicy Bypass -File "$dir\click.ps1" -X 1341 -Y 255 -WaitMs 2500 -Double | Out-Null

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 5
    try {
        $r = Invoke-RestMethod 'http://127.0.0.1:25580/state' -TimeoutSec 4 -ErrorAction Stop
        if ($r.ok) {
            Write-Output ("joined world at ({0},{1},{2})" -f [int]$r.x, [int]$r.y, [int]$r.z)
            exit 0
        }
    } catch { }
}
Write-Output 'NOT in world -- needs manual attention'
exit 1
