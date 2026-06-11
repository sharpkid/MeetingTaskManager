@echo off
chcp 65001 >nul
title 腾讯会议挂机系统 - 本地调试后端

echo ============================================
echo   腾讯会议挂机系统 - 本地调试后端
echo ============================================
echo.

:: 1. 检查 Python
echo [1/4] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.x
    echo 下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version

:: 2. 激活虚拟环境或安装依赖
echo.
echo [2/4] 检查依赖...
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo 虚拟环境已激活
) else (
    echo 虚拟环境不存在，正在创建...
    python -m venv venv
    call venv\Scripts\activate.bat
)

:: 安装依赖
pip install flask pymysql -q
echo 依赖安装完成

:: 3. 检查 MySQL
echo.
echo [3/4] 检查 MySQL 连接...
echo.
echo 注意：本地调试需要 MySQL 数据库。
echo 如果你本地没有 MySQL，有以下选择：
echo   A) 安装 MySQL（推荐）：https://dev.mysql.com/downloads/installer/
echo   B) 使用 Docker：docker run -p 3306:3306 -e MYSQL_ROOT_PASSWORD=Aw123456 -d mysql:8
echo   C) 连接远程服务器上的 MySQL（需修改 app.py 中的 MYSQL_HOST）
echo.
echo 当前数据库配置：
echo   主机: localhost
echo   用户: root
echo   密码: Aw123456
echo   库名: meeting_task_db
echo.

:: 4. 启动服务
echo [4/4] 启动 Flask 服务...
echo.
echo ============================================
echo   后端服务启动中...
echo   地址：http://localhost:8080
echo   管理页面：http://localhost:8080/
echo   按 Ctrl+C 停止服务
echo ============================================
echo.

python app.py

pause
