@echo off
chcp 65001 >nul
title 큐브 리셋
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0booth-reset-cube.ps1"
echo.
pause
