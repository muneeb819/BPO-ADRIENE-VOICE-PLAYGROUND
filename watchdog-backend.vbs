' BPO Nexus - silent watchdog launcher.
' wscript.exe is a GUI-subsystem host, so Task Scheduler never flashes a
' PowerShell/CMD window. The watchdog itself starts the backend with pythonw.
Option Explicit

Dim sh, cmd
Set sh = CreateObject("WScript.Shell")
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""C:\Users\Wave\Downloads\AdrieneVoiceStudio\watchdog-backend.ps1"" -Port 8010"
' 0 = hidden window, False = do not wait for it to finish
sh.Run cmd, 0, False
