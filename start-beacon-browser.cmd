@echo off
setlocal DisableDelayedExpansion

set "BEACON_ROOT=%~dp0"
set "DESKTOP_DIR=%BEACON_ROOT%desktop"
set "BEACON_URL=http://127.0.0.1:1420/"

if not exist "%DESKTOP_DIR%\package.json" (
  echo Beacon browser host was not found beside this launcher.
  echo See desktop\README.md for the supported local entry.
  exit /b 1
)

where node.exe >nul 2>nul
if errorlevel 1 (
  echo Node.js was not found. Install the Node.js version documented in desktop\README.md.
  exit /b 1
)

where npm.cmd >nul 2>nul
if errorlevel 1 (
  echo npm.cmd was not found. Install npm with the Node.js version documented in desktop\README.md.
  exit /b 1
)

if not exist "%DESKTOP_DIR%\node_modules\.bin\vite.cmd" (
  echo Desktop dependencies are missing. Follow desktop\README.md before running this launcher.
  echo This launcher never installs dependencies automatically.
  exit /b 1
)

powershell.exe -NoProfile -Command "try { $listener = Get-NetTCPConnection -State Listen -LocalPort 1420 -ErrorAction SilentlyContinue; if ($null -ne $listener) { exit 0 }; exit 1 } catch { exit 2 }" >nul 2>nul
set "BEACON_PORT_CHECK=%ERRORLEVEL%"
if "%BEACON_PORT_CHECK%"=="0" (
  echo Port 1420 is already in use. Stop the existing local service before starting Beacon browser host.
  exit /b 1
)
if not "%BEACON_PORT_CHECK%"=="1" (
  echo Could not verify whether port 1420 is available. See desktop\README.md for the supported local entry.
  exit /b 1
)

echo Starting Beacon browser host at %BEACON_URL%
echo Keep this window open. Press Ctrl+C or close this window to stop only this host.

powershell.exe -NoProfile -Command "$ErrorActionPreference = 'Stop'; $desktop = $env:DESKTOP_DIR; $url = $env:BEACON_URL; function Stop-OwnedProcessTree([int]$processId) { $children = Get-CimInstance Win32_Process -Filter ('ParentProcessId = ' + $processId) -ErrorAction SilentlyContinue; foreach ($child in $children) { Stop-OwnedProcessTree([int]$child.ProcessId) }; Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue }; $cancelled = $false; $handler = [ConsoleCancelEventHandler]{ param($sender, $event); $event.Cancel = $true; $script:cancelled = $true }; [Console]::add_CancelKeyPress($handler); $process = Start-Process -FilePath $env:ComSpec -ArgumentList @('/d', '/s', '/c', 'call npm.cmd run browser:dev') -WorkingDirectory $desktop -NoNewWindow -PassThru; try { $ready = $false; $deadline = [DateTime]::UtcNow.AddSeconds(20); while (-not $ready -and -not $cancelled -and [DateTime]::UtcNow -lt $deadline) { if ($process.HasExited) { break }; try { $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2; $ready = $response.StatusCode -ge 200 -and $response.StatusCode -lt 400 } catch {}; if (-not $ready) { Start-Sleep -Milliseconds 250 } }; if (-not $ready) { Write-Error 'Beacon browser host did not become ready within 20 seconds.'; Stop-OwnedProcessTree $process.Id; exit 1 }; if ($env:BEACON_BROWSER_NO_OPEN -ne '1') { Start-Process -FilePath $url }; Write-Host ('Beacon browser host is ready at ' + $url); while (-not $process.HasExited -and -not $cancelled) { Start-Sleep -Milliseconds 250; $process.Refresh() }; if ($cancelled -and -not $process.HasExited) { Stop-OwnedProcessTree $process.Id; exit 130 }; exit $process.ExitCode } finally { [Console]::remove_CancelKeyPress($handler); if ($cancelled -and -not $process.HasExited) { Stop-OwnedProcessTree $process.Id } }"
set "BEACON_EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %BEACON_EXIT_CODE%
