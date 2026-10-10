@echo off
rem Ярлык для запуска окна управления базой двойным щелчком.
rem Лежит в корне базы, программа - в tools\dbapp.
rem
rem Python программа ищет сама. Имя пользователя и папка установки
rem нигде не прописаны, поэтому файл работает на любом компьютере.
rem Если подходящий Python не найден - будет понятное сообщение.
rem
rem Внимание: имена файлов с русскими буквами cmd находит не всегда -
rem мешает кодировка консоли. Поэтому запускаем по имени main.py
rem (только латиница), а рабочую папку задаём заранее.
rem
rem Внимание: вертикальная черта (конвейер) в этом файле не используется -
rem на ней cmd спотыкается и обрывает работу.

setlocal

rem --- прячем окно консоли ----------------------------------------------
rem Окно консоли появляется раньше, чем выполняется первая строка этого
rem файла, поэтому спрятать его можно только отсюда. Окно ищется по имени,
rem которое мы сами только что поставили: чужие консоли не трогаются.
rem
rem Проверено на живых запусках: окно исчезает, потоки программы не
rem страдают. Если спрятать не вышло - продолжаем молча, лишнее окно
rem консоли лучше отказа запуска.
title OpenCodeBase-zapusk
powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass ^
  -File "%~dp0tools\dbapp\launchers\hide_console.ps1" -Marker "OpenCodeBase-zapusk"


set "DIR=%~dp0"
set "APPDIR=%DIR%tools\dbapp"
set "APP=%APPDIR%\main.py"
set "ERRF=%TEMP%\opencode-base-zapusk-ne-poluchilsya.txt"

if not exist "%APP%" goto :noapp

set "PYW="
set "PYW_FULL_DIR="
set "PYW_ANY_DIR="

rem 1. Python, установленный в систему. Новый установщик кладёт его в
rem    %LOCALAPPDATA%\Python\pythoncore-*, старый — в Programs\Python.
rem    Обычно он самый полный: есть и окна, и библиотеки мостов.
for /d %%D in ("%LOCALAPPDATA%\Python\pythoncore-*") do call :try_dir "%%~fD"
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do call :try_dir "%%~fD"
for /d %%D in ("%ProgramFiles%\Python*") do call :try_dir "%%~fD"

rem 2. Окружения, которые ставит сама программа. Они удваивают запуск
rem    (переадресатор venv поднимает второй процесс) и часто неполные,
rem    поэтому идут после системного Python.
for /d %%D in ("%USERPROFILE%\.workbuddy-ai\binaries\python\envs\*") do call :try_dir "%%~fD\Scripts"

rem 3. Python, прописанный в PATH.
for %%P in (python.exe) do call :try_exe "%%~$PATH:P"
for %%P in (pythonw.exe) do call :try_exe "%%~$PATH:P"

rem Полный вариант важнее: с ним работает проверка OBS вживую и автор
rem в цикле улучшения (он берёт тот же Python, что и программа). Но если
rem полного кандидата нет, программа всё равно должна открыться — тогда
rem берём любой, у которого есть окна PyQt6.
if defined PYW_FULL_DIR set "PYWDIR=%PYW_FULL_DIR%"
if not defined PYWDIR set "PYWDIR=%PYW_ANY_DIR%"
if not defined PYWDIR goto :nopython
if exist "%PYWDIR%pythonw.exe" set "PYW=%PYWDIR%pythonw.exe"
if not defined PYW set "PYW=%PYWDIR%python.exe"
if not defined PYW goto :nopython

rem --- запуск окна программы -------------------------------------------
rem Всё это окно консоли - единственное, что открывается при запуске.
rem Программа стартует сразу, а консоль живёт до проверки: если окно
rem программы открылось - консоль закрывается сама и больше не мешает.
rem Если окно не открылось - консоль остаётся и показывает причину.
rem
rem Признак «программа стартовала» берём не из внешнего окна, а из её
rem собственной метки единственного экземпляра: файл создаётся в
run() при старте. Так проверка не зависит от заголовков окон и от того,
rem на каком языке печатает cmd.

rem
rem PID читается через for /f, а НЕ через set /p. Программа пишет его
rem без перевода строки, и set /p такой файл не читает вовсе: переменная
rem остаётся пустой, проверка не проходит никогда, и лаунчер двадцать
rem секунд ждёт несуществующий PID, а потом открывает блокнот с ложью -
rem при том, что окно программы давно на экране. Проверено на одном и том же файле
rem без перевода строки: set /p даёт пусто, for /f даёт PID.
rem С переводом строки разницы нет, так что чтение одинаково в обоих
rem случаях и не зависит от того, как именно записан файл.
pushd "%APPDIR%"
start "" "%PYW%" -X utf8 "%APP%"
popd

set "LOCK=%TEMP%\opencode-base-dbapp-%USERNAME%.lock"
set /a _waited=0

:await_window
rem Пауза здесь через ping, а не через timeout. При перенаправленном
rem вводе timeout не ждёт, а сразу падает с ошибкой, и весь цикл
rem проходит за доли секунды: лаунчер успевает решить, что окно не
rem открылось, раньше чем программа вообще дошла до записи метки.
rem Проверено рядом на одинаковых вводных: timeout отработал сразу,
rem ping -n 2 127.0.0.1 - ровно за секунду.
ping -n 2 127.0.0.1 >nul
set /a _waited+=1
if not exist "%LOCK%" goto :wait_more
set "LOCKPID="
for /f "usebackq delims=" %%P in ("%LOCK%") do set "LOCKPID=%%P"
if not defined LOCKPID goto :wait_more
tasklist /fi "PID eq %LOCKPID%" /nh >nul 2>&1
if errorlevel 1 goto :wait_more
goto :window_open

:wait_more
if %_waited% lss 20 goto :await_window
goto :no_window

:window_open
rem Окно открылось: консоль закрывается, дальше работает только программа.
endlocal & exit /b 0

:no_window
>"%ERRF%" echo Окно программы не открылось за 20 секунд. Чаще всего это значит, что не запустился Python с окнами PyQt6.
echo.
echo Окно программы не открылось за 20 секунд.
echo Чаще всего это означает, что не запустился Python с окнами PyQt6.
echo Ниже - причина прямо из интерпретатора, если её удалось получить:
echo.
set "PYCONSOLE=%PYW:pythonw.exe=python.exe%"
"%PYCONSOLE%" -X utf8 "%APP%"
echo.
echo Программа завершилась с кодом %ERRORLEVEL%.
echo.
echo Если окно всё-таки открылось - закрой лишние экземпляры и запусти
echo программу ещё раз: при втором запуске она не откроется заново.
echo.
rem Паузы тут нет намеренно: консоль скрыта, и пауза держала
rem бы лаунчер молча. Причина и так показана в блокноте.
notepad "%ERRF%"
endlocal & exit /b 1

:try_dir
rem Проверяет Python в папке: сначала обычный, потом оконный. Запоминаем
rem папку целиком, поэтому хватает одной удачной проверки на папку:
rem python.exe и pythonw.exe всегда лежат рядом и умеют одно и то же.
if defined PYW_FULL_DIR if defined PYW_ANY_DIR exit /b
if "%~1"=="" exit /b
if not exist "%~1" exit /b
call :try_exe "%~1\python.exe"
if defined PYW_FULL_DIR exit /b
if defined PYW_ANY_DIR exit /b
call :try_exe "%~1\pythonw.exe"
exit /b

:try_exe
rem Годится ли этот Python. Нужны две вещи: окна PyQt6 — иначе нечего
rem открывать, и ещё requests с websockets — для проверки OBS вживую и
rem для автора в цикле улучшения. Сначала ищем того, у кого есть всё;
rem заглушку из Microsoft Store пропускаем: она лежит в WindowsApps,
rem ничего не делает и при этом отвечает, что всё хорошо.
if defined PYW_FULL_DIR if defined PYW_ANY_DIR exit /b
if "%~1"=="" exit /b
if not exist "%~1" exit /b
set "CAND=%~1"
set "SHORT=%CAND%"
call set "SHORT=%%SHORT:WindowsApps=%%"
if not "%SHORT%"=="%CAND%" exit /b
if defined PYW_FULL_DIR goto :try_any
"%CAND%" -c "import PyQt6, requests, websockets" >nul 2>&1
if not errorlevel 1 goto :is_full
:try_any
if defined PYW_ANY_DIR exit /b
"%CAND%" -c "import PyQt6" >nul 2>&1
if errorlevel 1 exit /b
set "PYW_ANY_DIR=%~dp1"
exit /b
:is_full
set "PYW_FULL_DIR=%~dp1"
exit /b

:nopython
>"%ERRF%" echo Не найден Python с окнами PyQt6 - без него окно не открыть. Установите Python 3 с сайта python.org и выполните: python -m pip install PyQt6
echo.
echo Не найден Python с окнами PyQt6 - без него окно не открыть.
echo.
echo Что делать: установите Python 3 с сайта python.org
echo (при установке отметьте галочку "Add Python to PATH"),
echo затем выполните в командной строке:
echo.
echo     python -m pip install PyQt6
echo.
echo Чтобы работали ещё и мосты, добавьте к этому:
echo.
echo     python -m pip install requests websockets
echo.
echo После этого запустите этот файл снова.
echo.
rem Паузы тут нет намеренно: консоль скрыта, и пауза держала
rem бы лаунчер молча. Причина и так показана в блокноте.
notepad "%ERRF%"
exit /b 1

:noapp
>"%ERRF%" echo Не найден файл программы main.py. Проверьте, что папка tools\dbapp есть рядом с этим файлом.
echo.
echo Не найден файл программы:
echo   %APP%
echo.
echo Проверьте, что папка tools\dbapp есть рядом с этим файлом.
echo.
rem Паузы тут нет намеренно: консоль скрыта, и пауза держала
rem бы лаунчер молча. Причина и так показана в блокноте.
notepad "%ERRF%"
exit /b 1
