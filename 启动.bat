@echo off
chcp 65001 >nul
title 英语朗读评测系统 - 启动中...

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║          英语朗读评测系统 - English Reading Scorer           ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

:: 检查 Docker 是否安装
where docker >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Docker！
    echo.
    echo 请先安装 Docker Desktop：
    echo https://www.docker.com/products/docker-desktop/
    echo.
    pause
    exit /b 1
)

:: 检查 Docker 是否运行
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] Docker 未运行，正在启动...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    echo 等待 Docker 启动（约 30 秒）...
    timeout /t 30 /nobreak >nul
)

:: 检查 .env 文件
if not exist .env (
    echo [提示] 未找到 .env 文件，正在创建...
    echo OPENAI_API_KEY=your-api-key-here > .env
    echo.
    echo [重要] 请编辑 .env 文件，填入你的 OpenAI API Key！
    echo.
    notepad .env
    pause
)

echo.
echo [1/3] 正在构建镜像（首次运行需要 5-10 分钟）...
docker-compose build

echo.
echo [2/3] 正在启动服务...
docker-compose up -d

echo.
echo [3/3] 等待服务就绪...
timeout /t 10 /nobreak >nul

:: 检查服务状态
docker-compose ps

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                      ✓ 启动成功！                            ║
echo ║                                                              ║
echo ║   打开浏览器访问：http://localhost                           ║
echo ║                                                              ║
echo ║   按任意键关闭此窗口（服务将继续在后台运行）                 ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

:: 自动打开浏览器
start http://localhost

pause >nul
