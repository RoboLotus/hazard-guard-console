@echo off
chcp 65001 >nul
title 운용 모드 끄기
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0booth-mode-off.ps1"
echo.
pause
