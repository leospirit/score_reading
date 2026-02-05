@echo off
chcp 65001 >nul
title 英语朗读评测系统 - 查看日志

echo 按 Ctrl+C 退出日志查看
echo.

docker-compose logs -f
