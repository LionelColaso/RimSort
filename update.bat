@echo off
setlocal enabledelayedexpansion

REM ========================================================================
REM RimSort Updater Script (Windows 10 & 11 Compatible)
REM Replaces app folder with downloaded update and launches new version
REM Usage: update.bat <temp_update_path> <log_path> <install_dir>
REM ========================================================================

REM Function to get timestamp
:GetTimestamp
set "timestamp=%date% %time%"
goto :eof

REM Function to log messages
:LogMessage
set "message=%~1"
call :GetTimestamp
if defined LOG_PATH (
    echo [%timestamp%] %message% >> "%LOG_PATH%"
) else (
    echo [%timestamp%] %message%
)
goto :eof

REM Function to check if RimSort is running
:IsRimSortRunning
tasklist /fi "imagename eq RimSort.exe" /fo csv 2>nul | find /i "RimSort.exe" >nul
goto :eof

REM Main update process
set "TEMP_UPDATE_PATH=%~1"
set "LOG_PATH=%~2"
set "INSTALL_DIR=%~3"

REM Validate arguments
if "%TEMP_UPDATE_PATH%" == "" (
    echo ERROR: Temp update path is required as first argument.
    call :LogMessage "ERROR: Temp update path is required as first argument."
    pause
    exit /b 1
)

if "%INSTALL_DIR%" == "" (
    echo ERROR: Install directory is required as third argument.
    call :LogMessage "ERROR: Install directory is required as third argument."
    pause
    exit /b 1
)

echo Starting RimSort update process...
call :LogMessage "INFO: Starting RimSort update process..."
echo Update source: %TEMP_UPDATE_PATH%
call :LogMessage "INFO: Temp update path: %TEMP_UPDATE_PATH%"

REM Get install directory (RimSort folder) and executable path
set "current_dir=%INSTALL_DIR%"
set "current_dir_no_slash=%current_dir:~0,-1%"
set "executable_path=%current_dir%RimSort.exe"

REM Normalize paths to use backslashes
if defined LOG_PATH (
    set "LOG_PATH=%LOG_PATH:/=\%"
)
set "TEMP_UPDATE_PATH=%TEMP_UPDATE_PATH:/=\%"
set "update_source_folder=%TEMP_UPDATE_PATH%"

call :LogMessage "INFO: Install directory: %INSTALL_DIR%"
call :LogMessage "INFO: Update source folder: %update_source_folder%"

REM Attempt to stop RimSort if it's already running
echo Stopping any running RimSort processes...
call :KillRimSort

REM Validate update source
echo Validating update source...
if not exist "%update_source_folder%" (
    echo ERROR: Update source folder does not exist: %update_source_folder%
    call :LogMessage "ERROR: Update source folder does not exist: %update_source_folder%"
    pause
    exit /b 1
)

if not exist "%update_source_folder%\RimSort.exe" (
    echo ERROR: RimSort.exe not found in update source folder.
    call :LogMessage "ERROR: RimSort.exe not found in update source folder."
    pause
    exit /b 1
)

echo Update source validated successfully.
call :LogMessage "INFO: Update source validated successfully."

REM Replace the current directory with the update folder
echo Replacing RimSort application folder...
call :LogMessage "INFO: Replacing RimSort folder..."
call :LogMessage "INFO: Source: %update_source_folder%"
call :LogMessage "INFO: Target: %current_dir_no_slash%"

REM Remove the current directory contents (but keep the directory itself)
rd /s /q "%current_dir_no_slash%" 2>nul
if exist "%current_dir_no_slash%" (
    echo ERROR: Failed to remove current directory.
    call :LogMessage "ERROR: Failed to remove current directory."
    pause
    exit /b 1
)

REM Move the update folder to the current location
move "%update_source_folder%" "%current_dir_no_slash%" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Failed to move update folder.
    call :LogMessage "ERROR: Failed to move update folder."
    pause
    exit /b 1
)

echo Folder replaced successfully.
call :LogMessage "SUCCESS: Folder replaced successfully."

REM Give time for filesystem to sync
ping -n 4 127.0.0.1 >nul

REM Verify the new executable exists
if exist "%executable_path%" (
    echo RimSort.exe verified after update.
    call :LogMessage "INFO: RimSort.exe verified after update."
) else (
    echo ERROR: RimSort.exe not found after update.
    call :LogMessage "ERROR: RimSort.exe not found after update."
    pause
    exit /b 1
)

REM Cleanup temp update files
echo Cleaning up temporary files...
call :LogMessage "INFO: Cleaning up temporary files..."
rd /s /q "%update_source_folder%" 2>nul
if exist "%update_source_folder%" (
    echo WARNING: Failed to remove temporary folder.
    call :LogMessage "WARNING: Failed to remove temporary folder."
) else (
    echo Temporary files cleaned up.
    call :LogMessage "INFO: Temporary files cleaned up."
)

REM Launch updated RimSort
echo Launching updated RimSort...
call :LogMessage "INFO: Launching updated RimSort..."
start "" "%executable_path%"

REM Confirm process launch
ping -n 3 127.0.0.1 >nul
call :IsRimSortRunning
if errorlevel 1 (
    echo WARNING: RimSort may not have started successfully.
    call :LogMessage "WARNING: RimSort may not have started successfully."
) else (
    echo SUCCESS: RimSort update completed and launched successfully!
    call :LogMessage "SUCCESS: RimSort update completed and launched successfully!"
)

exit /b 0

REM ------------------
REM Function to kill RimSort
REM ------------------
:KillRimSort
call :LogMessage "INFO: Stopping RimSort process..."
taskkill /F /im RimSort.exe >nul 2>&1
if errorlevel 1 (
    call :LogMessage "INFO: No running RimSort process found."
) else (
    call :LogMessage "INFO: RimSort process terminated."
    ping -n 3 127.0.0.1 >nul
)
goto :eof
