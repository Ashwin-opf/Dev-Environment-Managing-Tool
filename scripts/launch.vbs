Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
scriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
rootDir = FSO.GetParentFolderName(scriptDir)
WshShell.CurrentDirectory = rootDir
WshShell.Run "cmd.exe /c """ & FSO.BuildPath(scriptDir, "launch.bat") & """", 0, False
