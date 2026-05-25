@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\live-smoke.ps1" %*
