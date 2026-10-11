@echo off
chcp 65001 >nul
title 영상 복구
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0booth-recover-video.ps1"
echo.
pause
