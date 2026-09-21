$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workDir = Split-Path -Parent $scriptDir
$iconPath = Join-Path $workDir "src-tauri\icons\icon.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "PC Doctor.lnk"
$launchArgs = "-WindowStyle Hidden -NonInteractive -Command `"Set-Location -Path '$workDir'; `$env:PATH = 'C:\Program Files\nodejs;' + `$env:PATH; node scripts\start.js`""

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$shortcut.Arguments = $launchArgs
$shortcut.WorkingDirectory = $workDir
$shortcut.IconLocation = $iconPath
$shortcut.WindowStyle = 7
$shortcut.Description = 'PC Doctor - Intelligent Cross-Platform Developer Environment Manager'
$shortcut.Save()
Write-Host 'Shortcut created successfully at' $shortcutPath
