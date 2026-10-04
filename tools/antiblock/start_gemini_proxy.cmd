@echo off
chcp 65001 >nul
title Gemini through bypass
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_gemini_proxy.ps1"
pause
