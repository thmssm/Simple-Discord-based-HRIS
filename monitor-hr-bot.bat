@echo off
setlocal enabledelayedexpansion
title HRIS Bot Monitor

:: Force UTF-8 codepage (suppress error if unsupported)
chcp 65001 >nul 2>&1

:: ============================================================
::  HRIS Discord Bot — Real-Time Activity Monitor
::  Run from CMD: monitor-hr-bot.bat
::  Press Ctrl+C to stop any mode, then Q to quit
:: ============================================================

:: ══════════════════════════════════════════════════════════
::  CONFIGURATION — EDIT THESE BEFORE RUNNING
::  VPS_HOST = your server SSH address (e.g. ubuntu@192.168.1.100)
::  VPS_BOT_DIR = path to your bot installation on the server
::  DASHBOARD_URL = your dashboard domain or IP
:: ══════════════════════════════════════════════════════════
set VPS_HOST=ubuntu@your-server-ip
set VPS_BOT_DIR=.
set DASHBOARD_URL=https://dashboard.yourdomain.com
:: ══════════════════════════════════════════════════════════

:menu
cls
echo.
echo   +----------------------------------------------------+
echo   ^|      HRIS Discord Bot Activity Monitor             ^|
echo   +----------------------------------------------------+
echo.
echo   [1] Dashboard View      (SSH tunnel — structured API polling)
echo   [2] Bot Log Tail        (SSH — real-time raw events)
echo   [3] Journal Tail        (SSH — systemd service logs)
echo   [4] SQL Query Mode       (SSH — direct DB queries)
echo   [5] Health Monitor       (SSH tunnel — bot alive/dead status)
echo   [Q] Quit
echo.
set "choice="
set /p "choice=  Choose [1-5/Q]: "

if /i "%choice%"=="Q" goto :quit
if "%choice%"=="1" goto :dashboard
if "%choice%"=="2" goto :ssh_log
if "%choice%"=="3" goto :ssh_journal
if "%choice%"=="4" goto :sql_query
if "%choice%"=="5" goto :health
echo   Invalid choice. Try again.
timeout /t 1 >nul
goto :menu

:quit
echo   Bye.
timeout /t 1 >nul
exit /b

:: ============================================================
::  MODE 1 — Dashboard View (SSH Tunnel to local API)
:: ============================================================
:dashboard
cls
echo.
echo   +----------------------------------------------------+
echo   ^|   Mode: Dashboard View (SSH tunnel to API)          ^|
echo   ^|   Ctrl+C to stop, then Q to quit                    ^|
echo   +----------------------------------------------------+
echo.

set TUNNEL_PORT=18081
set REFRESH=10

:: Check for required tools
where ssh >nul 2>&1 || (
    echo   [ERR] OpenSSH not found. Install: Settings ^> Apps ^> Optional Features ^> OpenSSH Client
    pause
    goto :menu
)

where curl >nul 2>&1 || (
    echo   [ERR] curl not found.
    pause
    goto :menu
)

:: Kill any existing tunnel on our port
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%TUNNEL_PORT% .*LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

:: Start SSH tunnel in background
echo   [Starting SSH tunnel...]
start /B ssh -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -N -L %TUNNEL_PORT%:127.0.0.1:8081 %VPS_HOST%

:: Wait for tunnel
echo   [Waiting for tunnel to come up...]
set TUNNEL_OK=0
for /l %%i in (1,1,20) do (
    curl.exe -s --connect-timeout 2 --max-time 3 "http://127.0.0.1:%TUNNEL_PORT%/api/today" -o "%TEMP%\hr-probe.txt" 2>nul
    findstr /c:"active_voice" "%TEMP%\hr-probe.txt" >nul 2>&1
    if !errorlevel! equ 0 (
        set TUNNEL_OK=1
        goto :tunnel_ready
    )
    timeout /t 1 /nobreak >nul
)

:tunnel_ready
if %TUNNEL_OK% neq 1 (
    echo   [ERR] SSH tunnel failed.
    echo   Is the VPS reachable? Check VPS_HOST in the config section.
    pause
    goto :menu
)
echo   [OK] Tunnel established on localhost:%TUNNEL_PORT%

:: Login
echo   [Login required — Turnstile bypassed via localhost]
set "HR_USER="
set /p "HR_USER=  Username: "
if "%HR_USER%"=="" goto :menu

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$pwd=Read-Host -AsSecureString '  Password';[Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pwd))" > "%TEMP%\hr-pwd2.txt" 2>nul
set "HR_PASS="
set /p HR_PASS=<"%TEMP%\hr-pwd2.txt"
del "%TEMP%\hr-pwd2.txt" 2>nul

echo   [Logging in...]
curl.exe -s --connect-timeout 5 --max-time 10 -X POST -H "Content-Type: application/json" -d "{\"username\":\"%HR_USER%\",\"password\":\"%HR_PASS%\"}" "http://127.0.0.1:%TUNNEL_PORT%/api/login" -D "%TEMP%\hr-headers2.txt" -o "%TEMP%\hr-login2.json" 2>nul
set "HR_PASS="

set "SESSION_TOKEN="
for /f "tokens=2 delims=;=" %%a in ('findstr /i "Set-Cookie.*session=" "%TEMP%\hr-headers2.txt" 2^>nul') do set "SESSION_TOKEN=%%a"
if "%SESSION_TOKEN%"=="" (
    echo   [ERR] Login failed. Check credentials.
    type "%TEMP%\hr-login2.json" 2>nul
    echo.
    pause
    goto :menu
)
echo   [OK] Logged in. Polling every %REFRESH%s.
echo.

:dash_loop
cls
echo   ============ %date% %time:~0,8% ============
echo.

:: Fetch API
curl.exe -s --connect-timeout 5 --max-time 10 -H "Cookie: session=%SESSION_TOKEN%" "http://127.0.0.1:%TUNNEL_PORT%/api/today?_=%random%" -o "%TEMP%\hr-today2.json" 2>nul

if %errorlevel% neq 0 (
    echo   [ERR] Cannot reach dashboard. Retrying...
    timeout /t 3 /nobreak >nul
    goto :dash_loop
)

findstr /c:"active_voice" "%TEMP%\hr-today2.json" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [ERR] Session expired or API error. Reconnecting...
    timeout /t 2 /nobreak >nul
    goto :dashboard
)

:: Display with PowerShell (write script to temp file to avoid ^ issues)
(
echo $d=Get-Content '%TEMP%\hr-today2.json' -Raw^|ConvertFrom-Json;
echo Write-Host ('  ^> '+$d.date+' ^| '+(Get-Date -Format 'HH:mm:ss'^)^) -ForegroundColor White;
echo if($d.stats^){Write-Host ('  Sessions: '+$d.stats.total_voice_sessions+' ^| Active: '+$d.stats.active_now^) -ForegroundColor Gray}
echo if($d.active_voice.Count^){Write-Host ('  ACTIVE VOICE ('+$d.active_voice.Count+')'^) -ForegroundColor Cyan;foreach($u in $d.active_voice^){$n=if($u.user_name^){$u.user_name}else{$u.user_id};$c=if($u.channel_name^){$u.channel_name}else{'?'};$j=if($u.join_time.Length -ge 16^){$u.join_time.Substring(11,5^)}else{'--:--'};Write-Host ('    ^> '+$n.PadRight(22^).Substring(0,22^)+' ^| '+$c.PadRight(20^).Substring(0,20^)+' ^| since '+$j^) -ForegroundColor Green}}
echo if($d.voice_today.Count^){Write-Host ('  VOICE TODAY ('+$d.voice_today.Count+' sessions^)'^) -ForegroundColor Cyan;foreach($s in $d.voice_today^){$n=if($s.user_name^){$s.user_name.PadRight(18^).Substring(0,18^)}else{$s.user_id};$c=if($s.channel_name^){$s.channel_name.PadRight(16^).Substring(0,16^)}else{'?'};$j=if($s.join_time.Length -ge 16^){$s.join_time.Substring(11,5^)}else{'--:--'};$l=if($s.leave_time -and $s.leave_time.Length -ge 16^){$s.leave_time.Substring(11,5^)}else{'now'};$m=if($s.duration_minutes^){' '+[int]$s.duration_minutes+'m'}else{''};Write-Host ('    '+$n+' ^| '+$c+' ^| '+$j+'-'+$l+$m^) -ForegroundColor Yellow}}
echo if($d.upcoming_meetings.Count^){Write-Host ('  MEETINGS ('+$d.upcoming_meetings.Count+')'^) -ForegroundColor Magenta;foreach($m in $d.upcoming_meetings^){$st=$m.start_time.Substring(0,5^);$et=$m.end_time.Substring(0,5^);$c=if($m.channel_name^){$m.channel_name}else{'-'};$icon=if($m.status -eq 'concluded'^){[char]0x2713}else{'^>'};$color=if($m.status -eq 'concluded'^){'DarkGray'}else{'Magenta'};Write-Host ('    '+$icon+' '+$m.name.PadRight(24^).Substring(0,24^)+' ^| '+$st+'-'+$et+' ^| '+$c^) -ForegroundColor $color}}
echo if($d.absences.Count^){Write-Host ('  ABSENCES ('+$d.absences.Count+')'^) -ForegroundColor Red;foreach($a in $d.absences^){$n=if($a.user_name^){$a.user_name}else{$a.user_id};$t=if($a.absence_type^){$a.absence_type}else{'?'};$note=if($a.note^){' - '+$a.note}else{''};Write-Host ('    '+$n.PadRight(20^).Substring(0,20^)+' ^| '+$t.PadRight(12^).Substring(0,12^)+$note^) -ForegroundColor Red}}
echo Write-Host '';Write-Host ('  '+'-'*46^) -ForegroundColor DarkGray
) > "%TEMP%\hr-parse.ps1"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\hr-parse.ps1"

echo.
echo   Refreshing in %REFRESH%s... (Ctrl+C then Q to quit)
timeout /t %REFRESH% /nobreak >nul
goto :dash_loop

:: ============================================================
::  MODE 2 — SSH Bot Log Tail
:: ============================================================
:ssh_log
cls
echo.
echo   +----------------------------------------------------+
echo   ^|   Mode: Bot Log Tail (real-time)                    ^|
echo   ^|   Ctrl+C to stop, then Q to quit                    ^|
echo   +----------------------------------------------------+
echo.

where ssh >nul 2>&1 || (
    echo   [ERR] OpenSSH not found.
    pause
    goto :menu
)

echo   Connecting to %VPS_HOST% ...
echo   (Press Ctrl+C to stop, then Q at menu to quit)
echo.

ssh -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 %VPS_HOST% "tail -n 50 -f %VPS_BOT_DIR%/bot.log 2>/dev/null || journalctl -u hr-bot.service -f --no-pager"

echo.
echo   Disconnected.
pause
goto :menu

:: ============================================================
::  MODE 3 — SSH Journal Tail
:: ============================================================
:ssh_journal
cls
echo.
echo   +----------------------------------------------------+
echo   ^|   Mode: Journal Tail (systemd service)              ^|
echo   ^|   Ctrl+C to stop, then Q to quit                    ^|
echo   +----------------------------------------------------+
echo.

where ssh >nul 2>&1 || (
    echo   [ERR] OpenSSH not found.
    pause
    goto :menu
)

echo   Connecting to %VPS_HOST% ...
echo   (Press Ctrl+C to stop, then Q at menu to quit)
echo.

ssh -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 %VPS_HOST% "journalctl -u hr-bot.service -f --no-pager -o short-iso"

echo.
echo   Disconnected.
pause
goto :menu

:: ============================================================
::  MODE 4 — SQL Query Mode
:: ============================================================
:sql_query
cls
echo.
echo   +----------------------------------------------------+
echo   ^|   Mode: SQL Query (direct DB access via SSH)        ^|
echo   +----------------------------------------------------+
echo.
echo   Quick queries:
echo.
echo   [A] Active voice now
echo   [B] Voice sessions today (last 30)
echo   [C] Meetings today
echo   [D] Absences today
echo   [E] Today stats (all)
echo   [F] Custom query
echo   [M] Back to menu
echo.

where ssh >nul 2>&1 || (
    echo   [ERR] OpenSSH not found.
    pause
    goto :menu
)

set "QRY="
set /p "qchoice=  Choose [A-F/M]: "

if /i "%qchoice%"=="M" goto :menu
if /i "%qchoice%"=="A" set "QRY=SELECT user_name, channel_name, join_time FROM voice_sessions WHERE leave_time IS NULL ORDER BY channel_name, join_time;"
if /i "%qchoice%"=="B" set "QRY=SELECT user_name, channel_name, join_time, leave_time, CAST(duration_minutes AS INTEGER)||'m' as dur FROM voice_sessions WHERE date(join_time)=date('now','+7 hours') ORDER BY join_time DESC LIMIT 30;"
if /i "%qchoice%"=="C" set "QRY=SELECT name, start_time, end_time, channel_name FROM meetings WHERE date=date('now','+7 hours') AND cancelled=0 ORDER BY start_time;"
if /i "%qchoice%"=="D" set "QRY=SELECT user_name, absence_type, note FROM absences WHERE date=date('now','+7 hours') ORDER BY id;"
if /i "%qchoice%"=="E" (
    set "QRY=SELECT '--ACTIVE VOICE--'; SELECT user_name, channel_name, join_time FROM voice_sessions WHERE leave_time IS NULL; SELECT '--VOICE TODAY--'; SELECT COUNT(*) as sessions, COALESCE(SUM(duration_minutes),0) as total_min FROM voice_sessions WHERE date(join_time)=date('now','+7 hours'); SELECT '--MEETINGS--'; SELECT name, start_time, end_time, channel_name FROM meetings WHERE date=date('now','+7 hours') AND cancelled=0; SELECT '--ABSENCES--'; SELECT user_name, absence_type FROM absences WHERE date=date('now','+7 hours');"
)
if /i "%qchoice%"=="F" set /p "QRY=  Enter SQL: "

if "%QRY%"=="" (
    echo   No query selected.
    timeout /t 1 >nul
    goto :sql_query
)

cls
echo   Running query...
echo.

ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 %VPS_HOST% "sqlite3 -column -header %VPS_BOT_DIR%/hr.db \"%QRY%\""

echo.
pause
goto :sql_query

:: ============================================================
::  MODE 5 — Health Monitor
:: ============================================================
:health
cls
echo.
echo   +----------------------------------------------------+
echo   ^|   Mode: Health Monitor                              ^|
echo   ^|   Polling /api/health every 30s                     ^|
echo   ^|   Ctrl+C to stop, then Q to quit                    ^|
echo   +----------------------------------------------------+
echo.

set HEALTH_PORT=18082
set HEALTH_REFRESH=30

where ssh >nul 2>&1 || (
    echo   [ERR] OpenSSH not found.
    pause
    goto :menu
)

:: Kill existing tunnel on port
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%HEALTH_PORT% .*LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo   [Starting SSH tunnel on localhost:%HEALTH_PORT% ...]
start /B ssh -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -N -L %HEALTH_PORT%:127.0.0.1:8081 %VPS_HOST%

echo   [Waiting for tunnel...]
set HLTH_OK=0
for /l %%i in (1,1,15) do (
    curl.exe -s --connect-timeout 2 --max-time 3 "http://127.0.0.1:%HEALTH_PORT%/api/health" -o "%TEMP%\hr-hlth.txt" 2>nul
    findstr /c:"\"bot\"" "%TEMP%\hr-hlth.txt" >nul 2>&1
    if !errorlevel! equ 0 (
        set HLTH_OK=1
        goto :health_ready
    )
    timeout /t 1 /nobreak >nul
)

:health_ready
if %HLTH_OK% neq 1 (
    echo   [ERR] Tunnel failed. Is VPS reachable? Check VPS_HOST config.
    pause
    goto :menu
)
echo   [OK] Monitoring every %HEALTH_REFRESH%s. Green=alive Red=dead
echo.

:health_loop
curl.exe -s --connect-timeout 5 --max-time 10 "http://127.0.0.1:%HEALTH_PORT%/api/health" -o "%TEMP%\hr-hlth.json" 2>nul
if %errorlevel% neq 0 (
    echo   [%time:~0,8%] CONNECTION FAILED
    timeout /t %HEALTH_REFRESH% /nobreak >nul
    goto :health_loop
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$h=Get-Content '%TEMP%\hr-hlth.json' -Raw|ConvertFrom-Json;$bc=if($h.bot -eq 'alive'){'Green'}else{'Red'};$dc=if($h.dashboard -eq 'alive'){'Green'}else{'Red'};$a=if($h.last_heartbeat_sec_ago){[math]::Round($h.last_heartbeat_sec_ago,0)}else{'?'};Write-Host ('  ['+(Get-Date -Format 'HH:mm:ss')+']') -NoNewline -ForegroundColor White;Write-Host ('  Bot: ') -NoNewline;Write-Host ($h.bot.ToUpper()) -NoNewline -ForegroundColor $bc;Write-Host (' | heartbeat ') -NoNewline;Write-Host ([string]$a + 's ago') -NoNewline -ForegroundColor Gray;Write-Host (' | Service: '+$h.service) -NoNewline -ForegroundColor Gray;Write-Host (' | Dashboard: ') -NoNewline;Write-Host ($h.dashboard.ToUpper()) -ForegroundColor $dc"

timeout /t %HEALTH_REFRESH% /nobreak >nul
goto :health_loop
