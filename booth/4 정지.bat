@echo off
chcp 65001 >nul
title HazardGuard 정지
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0booth-stop.ps1"
echo.
pause
