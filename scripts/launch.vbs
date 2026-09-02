Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\srira\.gemini\antigravity\scratch\pc-doc"
WshShell.Run "cmd.exe /c """ & "C:\Users\srira\.gemini\antigravity\scratch\pc-doc\scripts\launch.bat" & """", 0, False
