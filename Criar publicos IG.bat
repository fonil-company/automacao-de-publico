@echo off
chcp 65001 >nul
cd /d "%~dp0"
py criar_publicos_ig.py %*
echo.
pause
