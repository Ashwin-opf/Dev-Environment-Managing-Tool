$iconPath = 'C:\Users\srira\.gemini\antigravity\scratch\pc-doc\src-tauri\icons\icon.ico'
$shortcutPath = 'C:\Users\srira\Desktop\PC Doctor.lnk'
$workDir = 'C:\Users\srira\.gemini\antigravity\scratch\pc-doc'
$launchArgs = '-WindowStyle Hidden -NonInteractive -Command "Set-Location -Path ''C:\Users\srira\.gemini\antigravity\scratch\pc-doc''; $env:PATH = ''C:\Program Files\nodejs;'' + $env:PATH; node scripts\start.js"'

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$shortcut.Arguments = $launchArgs
$shortcut.WorkingDirectory = $workDir
$shortcut.IconLocation = $iconPath
$shortcut.WindowStyle = 7
$shortcut.Description = 'PC Doctor - System Health Monitor'
$shortcut.Save()
Write-Host 'Shortcut created successfully'
