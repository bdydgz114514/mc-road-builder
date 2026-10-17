# Click a screen coordinate and optionally take a screenshot afterwards.
param(
    [int]$X = 1279,
    [int]$Y = 616,
    [int]$WaitMs = 1500,
    [switch]$Shot,
    [switch]$Double
)

Add-Type -AssemblyName System.Drawing
$code = @'
using System;
using System.Runtime.InteropServices;
public class W32c {
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
'@
Add-Type -TypeDefinition $code -Language CSharp

$proc = Get-Process -Name 'java' -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -match 'Minecraft' } | Select-Object -First 1
if ($proc -and $proc.MainWindowHandle -ne 0) {
    [W32c]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
    Start-Sleep -Milliseconds 600
}

Write-Output ("clicking screen ($X,$Y)" + $(if ($Double) { ' x2' } else { '' }))
[W32c]::SetCursorPos($X, $Y) | Out-Null
Start-Sleep -Milliseconds 300
[W32c]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero)
Start-Sleep -Milliseconds 80
[W32c]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)
if ($Double) {
    Start-Sleep -Milliseconds 120
    [W32c]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 80
    [W32c]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)
}
Write-Output 'clicked'
Start-Sleep -Milliseconds $WaitMs

if ($Shot) {
    Start-Sleep -Milliseconds 700
    $b = New-Object System.Drawing.Bitmap(2560, 1440)
    $g = [System.Drawing.Graphics]::FromImage($b)
    $g.CopyFromScreen(0, 0, 0, 0, $b.Size)
    $out = 'D:\mc-road-builder\mc-after-click.png'
    $b.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $b.Dispose()
    Write-Output ("screenshot: " + $out)
}
