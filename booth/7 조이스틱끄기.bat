@echo off
chcp 65001 >nul
title 조이스틱 끄기
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0booth-joystick-off.ps1"
echo.
pause
