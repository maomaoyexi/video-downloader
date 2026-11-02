@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONNOUSERSITE=1"
set "PYTHONHOME="
set "PYTHONPATH="
set "APP_ROOT=%~dp0"
cd /d "%APP_ROOT%"
if errorlevel 1 goto directory_error

echo 当前入口：v2.7.1 开发源码
echo 程序目录："%APP_ROOT%"
echo.

if not exist "%APP_ROOT%视频下载工具v2.7.1-GUI.py" goto source_missing
if not exist "%APP_ROOT%resource\launch_runtime.py" goto helper_missing

set "RUNTIME_PYTHON="
call :try_python "%APP_ROOT%dependency\python\python.exe"
call :try_python "%APP_ROOT%.venv\Scripts\python.exe"
call :try_python "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if defined RUNTIME_PYTHON goto run_source

for /f "delims=" %%P in ('py -3.12 -I -X utf8 -c "import sys; print(sys.executable)" 2^>nul') do call :try_python "%%P"
if defined RUNTIME_PYTHON goto run_source
for /f "delims=" %%P in ('where python 2^>nul') do call :try_python "%%P"
if defined RUNTIME_PYTHON goto run_source

echo [启动失败] 未找到可用的 64 位 Python 3.12。
echo 请安装 Python 3.12，或将对应运行环境放入 dependency\python。
echo 本启动器不会在线安装依赖，也不会改用旧版 EXE。
set "LAUNCH_EXIT=2"
goto finish_error

:run_source
echo Python："%RUNTIME_PYTHON%"
"%RUNTIME_PYTHON%" -I -X utf8 "%APP_ROOT%resource\launch_runtime.py" %*
set "LAUNCH_EXIT=%ERRORLEVEL%"
if "%LAUNCH_EXIT%"=="0" exit /b 0
echo.
echo [执行失败] 当前修复源码未正常完成，退出码：%LAUNCH_EXIT%
echo 详细错误已保留在上方；请勿以旧发布 EXE 的运行结果代替修复版。
goto finish_error

:directory_error
echo [启动失败] 无法进入启动器所在目录。
set "LAUNCH_EXIT=2"
goto finish_error

:source_missing
echo [启动失败] 当前目录缺少 视频下载工具v2.7.1-GUI.py。
set "LAUNCH_EXIT=2"
goto finish_error

:helper_missing
echo [启动失败] 当前目录缺少 resource\launch_runtime.py。
set "LAUNCH_EXIT=2"
goto finish_error

:finish_error
if "%~1"=="" pause
exit /b %LAUNCH_EXIT%

:try_python
if defined RUNTIME_PYTHON exit /b 0
if not exist "%~1" exit /b 0
"%~1" -I -X utf8 -c "import struct,sys; raise SystemExit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
set "RUNTIME_PYTHON=%~1"
exit /b 0
