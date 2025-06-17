@echo off

REM Ensure the application is killed
taskkill /F /im RimSort.exe >nul 2>&1
if errorlevel 1 (
    echo Warning: RimSort.exe process not found or could not be killed.
)

REM Set the update source folder
set "update_source_folder=%TEMP%\RimSort"

REM Check if update source folder exists
if not exist "%update_source_folder%" (
    echo Update source folder does not exist: %update_source_folder%
    exit /b 1
)

REM Display a message indicating the update operation is starting in 5 seconds
echo Updating RimSort in 5 seconds. Press any key to cancel.

REM Sleep for 5 seconds unless user input
choice /t 5 /d y /n >nul
if errorlevel 2 (
    echo Update cancelled by user.
    exit /b 1
)

REM Move files from the update source folder to the current directory
robocopy "%update_source_folder%" "%cd%" /MIR /NFL /NDL /NJH /NJS /nc /ns /np

REM Execute RimSort.exe from the current directory
start "" "%cd%\RimSort.exe"
