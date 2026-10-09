@echo off
chcp 65001 >nul
title HazardGuard 상태
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0booth-status.ps1"
echo.
pause
