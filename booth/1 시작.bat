@echo off
chcp 65001 >nul
title HazardGuard 시작
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0booth-start.ps1"
echo.
pause
