@echo off
chcp 65001 >nul
title 英语朗读评测系统 - 停止中...

echo.
echo 正在停止服务...
docker-compose down

echo.
echo ✓ 服务已停止
echo.
pause
