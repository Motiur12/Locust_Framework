@echo off
echo Deleting __pycache__ folders and .pyc files...

REM Delete __pycache__ directories
for /d /r . %%d in (__pycache__) do (
    if exist "%%d" (
        rd /s /q "%%d"
        echo Deleted folder: %%d
    )
)

REM Delete .pyc files
for /r %%f in (*.pyc) do (
    del /q "%%f"
    echo Deleted file: %%f
)

echo Cleanup complete.
pause
