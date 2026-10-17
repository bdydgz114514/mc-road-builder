# Screenshot the Minecraft window (or the whole screen) to find the menu buttons.
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

$code = @'
using System;
using System.Runtime.InteropServices;
public class W32s {
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
'@
Add-Type -TypeDefinition $code -Language CSharp

# find the Minecraft (LWJGL/GLFW) window
$proc = Get-Process -Name 'java' -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -match 'Minecraft' -or $_.MainWindowHandle -ne 0 } |
    Select-Object -First 1

if ($proc -and $proc.MainWindowHandle -ne 0) {
    $h = $proc.MainWindowHandle
    Write-Output ("window: pid=" + $proc.Id + " title='" + $proc.MainWindowTitle + "'")
    if ([W32s]::IsIconic($h)) { [W32s]::ShowWindow($h, 9) | Out-Null; Start-Sleep -Milliseconds 800 }
    [W32s]::SetForegroundWindow($h) | Out-Null
    Start-Sleep -Milliseconds 900
    $r = New-Object W32s+RECT
    [W32s]::GetWindowRect($h, [ref]$r) | Out-Null
    $w = $r.Right - $r.Left
    $hh = $r.Bottom - $r.Top
    Write-Output ("rect: " + $r.Left + ',' + $r.Top + "  " + $w + 'x' + $hh)
    if ($w -gt 100 -and $hh -gt 100) {
        $bmp = New-Object System.Drawing.Bitmap($w, $hh)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.CopyFromScreen($r.Left, $r.Top, 0, 0, $bmp.Size)
        $out = 'D:\mc-road-builder\mc-window.png'
        $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
        $g.Dispose(); $bmp.Dispose()
        Write-Output ("saved: " + $out)
        exit 0
    }
}

# fallback: whole screen
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap($b.Width, $b.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen(0, 0, 0, 0, $bmp.Size)
$out = 'D:\mc-road-builder\mc-screen.png'
$bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output ("no java window found; saved full screen: " + $out)
