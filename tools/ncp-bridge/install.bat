@echo off
chcp 65001 >nul
setlocal EnableExtensions
title NCP-Qwen bridge installer

rem ============================================================
rem  Установка моста между библиотекой NCP и Qwen Desktop.
rem
rem  Что делает:
rem    1. находит Python в системе (ни одного вписанного пути);
rem    2. запускает server.py --install;
rem    3. тот находит библиотеку, вписывает путь в config.json,
rem       прогоняет проверку и печатает настройки для Qwen.
rem
rem  Правила, по которым написан этот файл (добыты опытом):
rem    * ни одной вертикальной черты (даже в пояснении!) — она обрывает
rem      строку и cmd выдаёт «was unexpected at this time»;
rem    * нет цифры перед знаком перенаправления — cmd примет её
rem      за номер потока и молча потеряет строку;
rem    * все пути считаются от %~dp0, имя пользователя не вписано.
rem
rem  Для встройки в другую программу: задайте NCP_NOPAUSE=1,
rem  тогда ожидание нажатия клавиши в конце пропускается.
rem ============================================================

set "HERE=%~dp0"
set "PY="
set "WAIT=1"
if defined NCP_NOPAUSE set "WAIT="

echo.
echo ============================================================
echo  Мост NCP - Qwen: установка
echo ============================================================
echo.

rem --- 1. Python, которым пользуется программа управления базой ---
rem     Он лежит в домашней папке пользователя, а не рядом с базой,
rem     поэтому и путь считается от %USERPROFILE%.
rem     Скобки вокруг перечня обязательны: без них cmd выдаёт
rem     «... was unexpected at this time» и останавливается.
if exist "%USERPROFILE%\.workbuddy-ai\binaries\python\versions\current\python.exe" call :probe "%USERPROFILE%\.workbuddy-ai\binaries\python\versions\current\python.exe"

for /d %%V in ("%USERPROFILE%\.workbuddy-ai\binaries\python\versions\*") do (
    if exist "%%~fV\python.exe" call :probe "%%~fV\python.exe"
)
for /d %%E in ("%USERPROFILE%\.workbuddy-ai\binaries\python\envs\*") do (
    if exist "%%~fE\Scripts\python.exe" call :probe "%%~fE\Scripts\python.exe"
)

rem --- 1б. запасной случай: база перенесена вместе с окружением ---
for /d %%B in ("%HERE%..\*") do (
    for /d %%E in ("%%~fB\.workbuddy-ai\binaries\python\envs\*") do (
        if exist "%%~fE\Scripts\python.exe" call :probe "%%~fE\Scripts\python.exe"
    )
)

rem --- 2. обычные установки Python ---
for /d %%P in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%~fP\python.exe" call :probe "%%~fP\python.exe"
)
for /d %%P in ("%ProgramFiles%\Python*") do (
    if exist "%%~fP\python.exe" call :probe "%%~fP\python.exe"
)
for /d %%P in ("%ProgramFiles(x86)%\Python*") do (
    if exist "%%~fP\python.exe" call :probe "%%~fP\python.exe"
)

rem --- 3. Python из PATH (в самом конце: там бывает заглушка из Store) ---
call :probe "python.exe"
call :probe "py.exe"

if not defined PY goto :nopython

echo Найден Python:
echo   %PY%
echo.
"%PY%" "%HERE%server.py" --install %*
if errorlevel 1 goto :failed

echo.
echo Готово.
if defined WAIT pause
exit /b 0

:nopython
echo Python не найден.
echo.
echo Мосту нужен Python 3.8 или новее. Сторонние пакеты не нужны.
echo Поставьте Python с сайта python.org и при установке отметьте
echo галочку «Add Python to PATH», затем запустите install.bat заново.
echo.
if defined WAIT pause
exit /b 2

:failed
echo.
echo Установка завершилась с ошибкой — смотрите текст выше.
echo.
if defined WAIT pause
exit /b 1

rem ------------------------------------------------------------
rem  Проверяет, что найденный Python действительно запускается.
rem  Заглушка из Microsoft Store делает вид, что работает, поэтому
rem  её путь отсеивается по слову WindowsApps.
rem ------------------------------------------------------------
:probe
if defined PY goto :eof
"%~1" -c "import sys" >nul 2>&1
if errorlevel 1 goto :eof
set "CAND=%~1"
set "SHORT=%CAND%"
call set "SHORT=%%SHORT:WindowsApps=%%"
if not "%SHORT%"=="%CAND%" goto :eof
set "PY=%CAND%"
goto :eof
