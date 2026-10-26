@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Publicos do Instagram - deixe esta janela aberta
py interface.py
pause
