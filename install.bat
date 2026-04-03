@echo off
REM Finance OS — Windows Installer
REM Run: install.bat

echo.
echo   Finance OS Installer
echo   =====================
echo   Local-first personal finance intelligence
echo.

REM Check Python
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo   ERROR: Python 3 is required. Install from https://python.org
    pause
    exit /b 1
)

REM Create install directory
set INSTALL_DIR=%USERPROFILE%\.financeos-app
echo   Installing to %INSTALL_DIR%

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

REM Copy app files
xcopy /E /Y /Q "%~dp0*.py" "%INSTALL_DIR%\" >nul
xcopy /E /Y /Q "%~dp0routers" "%INSTALL_DIR%\routers\" >nul
xcopy /E /Y /Q "%~dp0services" "%INSTALL_DIR%\services\" >nul
xcopy /E /Y /Q "%~dp0templates" "%INSTALL_DIR%\templates\" >nul
xcopy /E /Y /Q "%~dp0static" "%INSTALL_DIR%\static\" >nul
xcopy /E /Y /Q "%~dp0samples" "%INSTALL_DIR%\samples\" >nul
copy /Y "%~dp0requirements.txt" "%INSTALL_DIR%\" >nul

REM Create venv and install deps
echo   Setting up Python environment...
python -m venv "%INSTALL_DIR%\venv"
"%INSTALL_DIR%\venv\Scripts\pip" install -q -r "%INSTALL_DIR%\requirements.txt"

REM Create launcher
echo @echo off > "%INSTALL_DIR%\FinanceOS.bat"
echo cd /d "%%~dp0" >> "%INSTALL_DIR%\FinanceOS.bat"
echo call venv\Scripts\activate >> "%INSTALL_DIR%\FinanceOS.bat"
echo python main.py %%* >> "%INSTALL_DIR%\FinanceOS.bat"

echo.
echo   Installation complete!
echo.
echo   To run:  %INSTALL_DIR%\FinanceOS.bat
echo.
echo   Data stored at: %%USERPROFILE%%\.financeos\finance.db
echo   100%% local. Nothing leaves your machine.
echo.
pause
