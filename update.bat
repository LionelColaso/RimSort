@echo off
setlocal EnableDelayedExpansion
REM Show the window
title RimSort Update
mode con: cols=100 lines=30
echo RimSort update in progress... Please wait.

REM ========================================================================
REM RimSort Updater Script (Windows 10 & 11 Compatible)
REM Safely backs up and updates RimSort from provided temp path
REM Usage: update.bat <temp_update_path> <log_path> [app_folder]
REM ========================================================================

REM Get arguments
set "TEMP_UPDATE_PATH=%~1"
set "LOG_PATH=%~2"
set "APP_FOLDER=%~3"

REM Validate arguments
if "%TEMP_UPDATE_PATH%" == "" (
    echo ERROR: Temp update path is required as first argument.
    if defined LOG_PATH (
        echo [%date% %time%] ERROR: Temp update path is required as first argument. >> "%LOG_PATH%"
    )
    pause
    exit /b 1
)

REM Validate temp update path exists
if not exist "%TEMP_UPDATE_PATH%" (
    echo ERROR: Temp update path does not exist: %TEMP_UPDATE_PATH%
    if defined LOG_PATH (
        echo [%date% %time%] ERROR: Temp update path does not exist: %TEMP_UPDATE_PATH% >> "%LOG_PATH%"
    )
    pause
    exit /b 1
)

REM Get current directory (should be application folder)
if defined APP_FOLDER (
    set "current_dir=%APP_FOLDER%"
) else (
    set "current_dir=%CD%"
)

REM Validate current directory
if not exist "%current_dir%" (
    echo ERROR: Application folder does not exist: %current_dir%
    if defined LOG_PATH (
        echo [%date% %time%] ERROR: Application folder does not exist: %current_dir% >> "%LOG_PATH%"
    )
    pause
    exit /b 1
)

REM Remove trailing backslash for cleaner paths
if "!current_dir:~-1!"=="\" (
    set "current_dir_no_slash=!current_dir:~0,-1!"
) else (
    set "current_dir_no_slash=!current_dir!"
)

set "executable_path=!current_dir_no_slash!\RimSort.exe"
set "update_source_folder=%TEMP_UPDATE_PATH%"

REM Log start
if defined LOG_PATH (
    echo [%date% %time%] INFO: Starting RimSort update process... >> "%LOG_PATH%"
    echo [%date% %time%] INFO: Temp update path: !update_source_folder! >> "%LOG_PATH%"
    echo [%date% %time%] INFO: App folder: !current_dir_no_slash! >> "%LOG_PATH%"
    echo [%date% %time%] INFO: Log path: %LOG_PATH% >> "%LOG_PATH%"
) else (
    echo [%date% %time%] INFO: Starting RimSort update process...
    echo [%date% %time%] INFO: Temp update path: !update_source_folder!
    echo [%date% %time%] INFO: App folder: !current_dir_no_slash!
)

REM Attempt to stop RimSort if it's already running
if defined LOG_PATH (
    echo [%date% %time%] INFO: Stopping RimSort process... >> "%LOG_PATH%"
) else (
    echo [%date% %time%] INFO: Stopping RimSort process...
)
taskkill /F /im RimSort.exe >nul 2>&1
if errorlevel 1 (
    if defined LOG_PATH (
        echo [%date% %time%] INFO: No running RimSort process found. >> "%LOG_PATH%"
    ) else (
        echo [%date% %time%] INFO: No running RimSort process found.
    )
) else (
    if defined LOG_PATH (
        echo [%date% %time%] INFO: RimSort process terminated. >> "%LOG_PATH%"
    ) else (
        echo [%date% %time%] INFO: RimSort process terminated.
    )
    ping -n 3 127.0.0.1 >nul
)

REM Check if RimSort.exe exists in the update folder
if not exist "%update_source_folder%\RimSort.exe" (
    if defined LOG_PATH (
        echo [%date% %time%] ERROR: RimSort.exe not found in update source folder: %update_source_folder% >> "%LOG_PATH%"
    ) else (
        echo [%date% %time%] ERROR: RimSort.exe not found in update source folder: %update_source_folder%
    )
    pause
    exit /b 1
)

REM Show update information
echo.
echo ========================================================================
echo RimSort Update Ready
echo Source: !update_source_folder!
echo Target: !current_dir_no_slash!
echo.
echo The update will start automatically...
echo ========================================================================
if defined LOG_PATH (
    echo. >> "%LOG_PATH%"
    echo RimSort Update Ready >> "%LOG_PATH%"
    echo Source: !update_source_folder! >> "%LOG_PATH%"
    echo Target: !current_dir_no_slash! >> "%LOG_PATH%"
    echo. >> "%LOG_PATH%"
    echo The update will start automatically... >> "%LOG_PATH%"
    echo ======================================================================== >> "%LOG_PATH%"
)

REM Begin update by copying files from temp update folder to app folder
if defined LOG_PATH (
    echo [%date% %time%] INFO: Updating RimSort files... >> "%LOG_PATH%"
    echo [%date% %time%] INFO: Source: !update_source_folder! >> "%LOG_PATH%"
    echo [%date% %time%] INFO: Target: !current_dir_no_slash! >> "%LOG_PATH%"
) else (
    echo [%date% %time%] INFO: Updating RimSort files...
    echo [%date% %time%] INFO: Source: !update_source_folder!
    echo [%date% %time%] INFO: Target: !current_dir_no_slash!
)

REM Use robocopy for file copying with error handling
if defined LOG_PATH (
    echo [%date% %time%] INFO: Starting robocopy operation... >> "%LOG_PATH%"
    echo [%date% %time%] INFO: Source: !update_source_folder! >> "%LOG_PATH%"
    echo [%date% %time%] INFO: Target: !current_dir_no_slash! >> "%LOG_PATH%"
)
echo Source: !update_source_folder!
echo Target: !current_dir_no_slash!
robocopy "!update_source_folder!" "!current_dir_no_slash!" /E /COPY:DAT /R:3 /W:5 /NFL /NDL
set "robocopy_exit=!errorlevel!"
if defined LOG_PATH (
    echo [%date% %time%] INFO: Robocopy completed with exit code: !robocopy_exit! >> "%LOG_PATH%"
)
echo Robocopy exit code: !robocopy_exit!

REM Robocopy exit codes: 0=no errors, 1=files copied, 2=extra files, 4=mismatches, 8=some failures, 16=serious error
REM For update, 0, 1, 2, 4 are generally acceptable
if !robocopy_exit! LEQ 4 goto :robocopy_success
goto :robocopy_error

:robocopy_success
if defined LOG_PATH (
    echo [%date% %time%] INFO: Files copied successfully. >> "%LOG_PATH%"
) else (
    echo [%date% %time%] INFO: Files copied successfully.
)
goto :robocopy_done

:robocopy_error
if defined LOG_PATH (
    echo [%date% %time%] ERROR: Update failed during file copy. Robocopy exit code: !robocopy_exit! >> "%LOG_PATH%"
) else (
    echo [%date% %time%] ERROR: Update failed during file copy. Robocopy exit code: !robocopy_exit!
)
pause
exit /b 1

:robocopy_done

REM Give time for filesystem to sync
ping -n 4 127.0.0.1 >nul

REM Verify the new executable exists
if exist "!executable_path!" (
    if defined LOG_PATH (
        echo [%date% %time%] INFO: RimSort.exe verified after update. >> "%LOG_PATH%"
    ) else (
        echo [%date% %time%] INFO: RimSort.exe verified after update.
    )
) else (
    if defined LOG_PATH (
        echo [%date% %time%] ERROR: RimSort.exe not found after update. Expected at: !executable_path! >> "%LOG_PATH%"
    ) else (
        echo [%date% %time%] ERROR: RimSort.exe not found after update. Expected at: !executable_path!
    )
    pause
    exit /b 1
)

REM Cleanup temp update files
if defined LOG_PATH (
    echo [%date% %time%] INFO: Cleaning up temporary files... >> "%LOG_PATH%"
    echo [%date% %time%] INFO: Removing: !update_source_folder! >> "%LOG_PATH%"
) else (
    echo [%date% %time%] INFO: Cleaning up temporary files...
    echo [%date% %time%] INFO: Removing: !update_source_folder!
)

REM Remove temp folder with retry logic
set "cleanup_retries=3"
:cleanup_retry
if !cleanup_retries! LEQ 0 (
    if defined LOG_PATH (
        echo [%date% %time%] WARNING: Failed to remove temporary folder after retries. >> "%LOG_PATH%"
    ) else (
        echo [%date% %time%] WARNING: Failed to remove temporary folder after retries.
    )
    goto :cleanup_done
)

rd /s /q "!update_source_folder!" 2>nul
if exist "!update_source_folder!" (
    set /a cleanup_retries-=1
    ping -n 2 127.0.0.1 >nul
    goto :cleanup_retry
) else (
    if defined LOG_PATH (
        echo [%date% %time%] INFO: Temporary files cleaned up. >> "%LOG_PATH%"
    ) else (
        echo [%date% %time%] INFO: Temporary files cleaned up.
    )
)

:cleanup_done

REM Launch updated RimSort
if defined LOG_PATH (
    echo [%date% %time%] INFO: Launching RimSort from: !executable_path! >> "%LOG_PATH%"
) else (
    echo [%date% %time%] INFO: Launching RimSort from: !executable_path!
)

REM Give additional time for files to fully settle
ping -n 2 127.0.0.1 >nul

REM Start RimSort with better error handling
if exist "!executable_path!" (
    echo Launching: !executable_path!
    
    REM Use PowerShell to start the process for better reliability
    powershell -NoProfile -Command "Start-Process '!executable_path!' -WorkingDirectory '!current_dir_no_slash!'" 2>nul
    
    REM If PowerShell fails, try direct method
    if errorlevel 1 (
        if defined LOG_PATH (
            echo [%date% %time%] INFO: PowerShell launch failed, trying direct method. >> "%LOG_PATH%"
        )
        start "" "!executable_path!"
    )
    
    REM Wait for process to fully start
    ping -n 6 127.0.0.1 >nul
) else (
    if defined LOG_PATH (
        echo [%date% %time%] ERROR: RimSort.exe not found at: !executable_path! >> "%LOG_PATH%"
    ) else (
        echo [%date% %time%] ERROR: RimSort.exe not found at: !executable_path!
    )
    echo.
    echo ERROR: RimSort.exe not found at expected location: !executable_path!
    echo.
    echo Press any key to close this window...
    pause >nul
    exit /b 1
)

REM Confirm process launch (retry up to 5 times with longer wait)
set "launch_confirmed=0"
set "attempt=0"
:check_launch
set /a attempt+=1
if !attempt! gtr 5 goto :launch_complete

tasklist /fi "imagename eq RimSort.exe" /fo csv | find /i "RimSort.exe" >nul
if not errorlevel 1 (
    set "launch_confirmed=1"
    goto :launch_success
)
ping -n 3 127.0.0.1 >nul
goto :check_launch

:launch_complete

:launch_success
if !launch_confirmed! EQU 1 (
    if defined LOG_PATH (
        echo [%date% %time%] INFO: RimSort update completed and launched successfully! >> "%LOG_PATH%"
    ) else (
        echo [%date% %time%] INFO: RimSort update completed and launched successfully!
    )
    echo.
    echo Update completed successfully! The new RimSort version is now running.
    echo This window will close automatically in 5 seconds...
    ping -n 6 127.0.0.1 >nul
) else (
    if defined LOG_PATH (
        echo [%date% %time%] WARNING: RimSort may not have started. >> "%LOG_PATH%"
        echo [%date% %time%] INFO: You can start it manually from: !executable_path! >> "%LOG_PATH%"
    ) else (
        echo [%date% %time%] WARNING: RimSort may not have started.
        echo [%date% %time%] INFO: You can start it manually from: !executable_path!
    )
    echo.
    echo Note: RimSort may still be starting in the background.
    echo Press any key to close this window...
    pause >nul
)



exit /b 0
