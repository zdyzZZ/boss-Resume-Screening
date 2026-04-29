@echo off
chcp 65001 >nul
cd /d %~dp0
echo ========================================
echo 简历筛选系统启动中...
echo ========================================
python app.py
pause
