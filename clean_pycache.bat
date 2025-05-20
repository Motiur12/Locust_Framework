@echo off
setlocal enabledelayedexpansion
echo Deleting __pycache__ folders and .pyc files...

REM Delete __pycache__ directories
for /d /r %%d in (__pycache__) do (
    if exist "%%d" (
        echo Deleting folder: %%d
        rd /s /q "%%d"
    )
)

REM Delete .pyc files
for /r %%f in (*.pyc) do (
    if exist "%%f" (
        echo Deleting file: %%f
        del /q "%%f"
    )
)

echo Cleanup complete.
pause

