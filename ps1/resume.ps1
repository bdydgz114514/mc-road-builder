# resume.ps1 -- 一条命令把整条链拉起来（施工 + 守护 + 截图 + 守命 + 看门狗）
#
# 前置：游戏已经启动并进服（bridge 能 /ping 通）。
#       如果游戏没开，先跑 .\launch-mc.ps1
#
# 用法：
#   .\resume.ps1              # 从 west_end.txt 的断点继续
#   .\resume.ps1 -Start -1200 # 强制从指定列开始
# 停止：
#   写 HALT 文件后 runner 会暂停；要彻底停就 Kill-Python

param(
    [int]$Start = 0,
    [int]$End = -7888,
    [double]$Hours = 9,
    [int]$Batch = 14,
    [double]$MinHp = 2
)

$here = 'D:\mc-road-builder'
Set-Location $here
$env:PYTHONIOENCODING = 'utf-8'

# 0) 桥是否活着
$ping = & python -c "import aic;print(aic.get('/ping').get('ok'))" 2>$null
if ($ping -ne 'True') {
    Write-Host "!! 桥不通（25580）—— 先把游戏开起来并进服：.\launch-mc.ps1" -ForegroundColor Red
    exit 1
}

# 1) 清掉上次的停机旗标
if (Test-Path HALT) { Remove-Item HALT; Write-Host 'cleared HALT' }

# 2) 断点
if ($Start -eq 0) {
    if (Test-Path west_end.txt) { $Start = [int](Get-Content west_end.txt -Raw) }
    else { $Start = -1000 }
}
Write-Host "从 x=$Start 铺到 x=$End，每批 $Batch 列，预算 $Hours 小时" -ForegroundColor Cyan

# 3) 守护们（全部脱离式，关窗口也不影响）
Start-Process python -ArgumentList 'watchdog.py','--poll','2','--only-prefix','G','--allow','Guxiaoge','--auto-resume' -WorkingDirectory $here -WindowStyle Hidden
Start-Process python -ArgumentList 'shots_daemon.py','--interval','15','--keep','960' -WorkingDirectory $here -WindowStyle Hidden
Start-Process python -ArgumentList 'keeplive.py','--seconds','28800' -WorkingDirectory $here -WindowStyle Hidden
Start-Process python -ArgumentList 'runner.py','--start',"$Start",'--end',"$End",'--hours',"$Hours",'--batch',"$Batch",'--min-hp',"$MinHp" -WorkingDirectory $here -WindowStyle Hidden -RedirectStandardOutput "$here\runner_out.log" -RedirectStandardError "$here\runner_err.log"

Start-Sleep -Seconds 6
Write-Host "`n--- 进程 ---" -ForegroundColor Cyan
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ForEach-Object {
    "PID $($_.ProcessId): " + ($_.CommandLine -replace '.*python\.exe"?\s*', '')
}
Write-Host "`n日志：runner_out.log / watchdog.log / keeplive.log / shots_daemon.log" -ForegroundColor Gray
