@echo off
setlocal
set APP_DIR=%~dp0
set PATH=%APP_DIR%vlc;%PATH%
python "%APP_DIR%main.py"
