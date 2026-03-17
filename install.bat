@echo off
REM Kalien Farmer — One-line installer for Windows.
REM Automatically installs Python if missing, then runs setup.

echo.
echo   Kalien Farmer Installer
echo   ======================
echo.

REM ── Check Python ──
where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    python -c "import sys; exit(0 if sys.version_info >= (3,8) else 1)" >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        echo   [OK]   Python found
        goto :HAS_PYTHON
    )
)

echo   [INFO] Python not found — installing automatically...
echo.

REM Try winget first (built into Windows 10/11)
where winget >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo   [INFO] Installing Python via winget...
    winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    if %ERRORLEVEL% equ 0 (
        echo   [OK]   Python installed via winget
        echo   [INFO] Refreshing PATH...
        REM Refresh PATH by re-reading from registry
        for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYSPATH=%%b"
        for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USRPATH=%%b"
        set "PATH=%SYSPATH%;%USRPATH%"
        goto :CHECK_AGAIN
    )
)

REM Fallback: download installer directly
echo   [INFO] Downloading Python installer...
set "PYURL=https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe"
set "PYINST=%TEMP%\python-installer.exe"
powershell -Command "Invoke-WebRequest -Uri '%PYURL%' -OutFile '%PYINST%'" 2>nul
if not exist "%PYINST%" (
    echo   [FAIL] Download failed. Install Python manually from https://www.python.org/downloads/
    pause
    exit /b 1
)
echo   [INFO] Running Python installer (this may take a minute)...
echo   [INFO] If a UAC prompt appears, click Yes.
"%PYINST%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
if %ERRORLEVEL% neq 0 (
    echo   [WARN] Silent install failed — launching interactive installer.
    echo   [INFO] IMPORTANT: Check "Add Python to PATH" at the bottom of the installer!
    "%PYINST%" PrependPath=1
)
del "%PYINST%" 2>nul

REM Refresh PATH
for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYSPATH=%%b"
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USRPATH=%%b"
set "PATH=%SYSPATH%;%USRPATH%"

:CHECK_AGAIN
where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo   [OK]   Python ready
    goto :HAS_PYTHON
)
REM Try common install locations
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
    echo   [OK]   Python found at default install location
    goto :HAS_PYTHON
)

echo   [FAIL] Python still not found after install.
echo   [INFO] Close this window, open a NEW command prompt, and run install.bat again.
pause
exit /b 1

:HAS_PYTHON
echo.

REM ── Run setup ──
if exist setup.py (
    python setup.py %*
    if %ERRORLEVEL% equ 0 (
        echo.
        echo   Setup complete! Starting Kalien Farmer...
        echo.
        python kalien-farmer.py
    )
) else if exist kalien-farmer\setup.py (
    cd kalien-farmer
    python setup.py %*
    if %ERRORLEVEL% equ 0 (
        echo.
        echo   Setup complete! Starting Kalien Farmer...
        echo.
        python kalien-farmer.py
    )
) else (
    echo   [INFO] Downloading Kalien Farmer...
    where git >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        git clone https://github.com/AshFrancis/kalien-farmer.git
        cd kalien-farmer
        python setup.py %*
    ) else (
        echo   [INFO] Downloading zip...
        powershell -Command "Invoke-WebRequest -Uri 'https://github.com/AshFrancis/kalien-farmer/archive/refs/heads/main.zip' -OutFile 'kalien-farmer.zip'"
        powershell -Command "Expand-Archive -Path 'kalien-farmer.zip' -DestinationPath '.' -Force"
        move kalien-farmer-main kalien-farmer >nul 2>&1
        del kalien-farmer.zip 2>nul
        cd kalien-farmer
        python setup.py %*
    )
)

if %ERRORLEVEL% neq 0 (
    echo.
    echo   Setup had errors — check the output above.
    pause
)
