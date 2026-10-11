@echo off
chcp 65001 >nul
title 조이스틱 켜기
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0booth-joystick-on.ps1"
echo.
pause
