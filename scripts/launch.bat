@echo off
title PC Doctor
cd /d "%~dp0.."
set PATH=C:\Program Files\nodejs;%PATH%
node scripts/start.js
