[CmdletBinding()]
param(
    [int]$FacadeDefaultPort = 17890,
    [int]$XrayPort = 10900
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

# Запуск Gemini через обход блокировок.
#
# Что делает: поднимает наш Xray и переводчик-фасад, потом запускает
# настольное приложение Gemini уже с ключом --proxy-server. Приложение
# само и не знает, что ходит через обход: Chromium просто отправляет все
# запросы на локальный порт фасада, а тот уже через живой VLESS-узел.
#
# Почему не через DNS: часть VPN-клиентов (у нас это INCY) перехватывает
# системный DNS и подсовывает свои адреса. Приложение идёт мимо этого
# перехвата, потому что адрес фасада — 127.0.0.1, а не домен.
#
# --disable-quic обязателен: без него Chromium пытается идти по QUIC
# (UDP 443), а прокси такой трафик не передаёт, и соединение молча умирает.
#
# Ничего глобального не меняется: ни DNS, ни настройки Windows. Работает
# только пока запущены фасад и Xray. Закрыл окно Gemini — фасад можно
# закрыть вручную (он сам не мешает).

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Порт фасада берётся из настроек программы, а не из константы в коде:
# ключ facade_port в <папка программы>\config\preferences.json.
# Функция ниже объясняет, откуда стартер знает путь к папке программы.
function Get-FacadePort {
    # Порт фасада — настройка программы, лежит в файле
    # <папка программы>\config\preferences.json, ключ facade_port.
    #
    # Где лежит папка программы, стартер узнаёт из манифеста набора
    # (.opencode-base-caps.json, ключ antiblock_base) — он лежит рядом с
    # папкой стартеров, на уровень выше. Запасной путь — подъём вверх от
    # $PSScriptRoot: он работает для копии стартера внутри папки программы
    # и не работает для рабочей копии (это другое дерево, до Downloads
    # подъём не доходит), поэтому он именно запасной.
    #
    # Молча откатываться на дефолт нельзя: человек правил настройку и
    # должен увидеть, что она не учтена.
    param([int]$Default, [int]$XrayPort)

    $prefs = ""
    $capsDir = Split-Path -Parent $PSScriptRoot
    $manifest = Join-Path $capsDir ".opencode-base-caps.json"
    if (Test-Path -LiteralPath $manifest) {
        try {
            $caps = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
            $base = $caps.antiblock_base
            if ($base) {
                $candidate = Join-Path ([string]$base) "config\preferences.json"
                if (Test-Path -LiteralPath $candidate) {
                    $prefs = $candidate
                }
                else {
                    Write-Host ("Путь к программе из манифеста не подошёл: {0}" -f $candidate)
                }
            }
        }
        catch {
            Write-Host ("Манифест набора не прочитан: {0}" -f $_.Exception.Message)
        }
    }
    if (-not $prefs) {
        $dir = $PSScriptRoot
        while ($dir) {
            $candidate = Join-Path $dir "config\preferences.json"
            if (Test-Path -LiteralPath $candidate) { $prefs = $candidate; break }
            $parent = Split-Path -Parent $dir
            if (-not $parent -or $parent -eq $dir) { break }
            $dir = $parent
        }
    }
    if (-not $prefs) {
        Write-Host ("Файл настроек не найден ни в манифесте, ни выше по дереву. Взят порт {0}." -f $Default)
        return $Default
    }
    try {
        $data = Get-Content -LiteralPath $prefs -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        Write-Host ("Файл настроек {0} не прочитан: {1}. Взят порт {2}." -f $prefs, $_.Exception.Message, $Default)
        return $Default
    }
    if ($null -eq $data -or $null -eq $data.facade_port) { return $Default }
    $raw = $data.facade_port
    if (-not ($raw -is [int] -or $raw -is [long])) {
        Write-Host ("Порт в настройке не целое число: {0}. Взят {1}." -f $raw, $Default)
        return $Default
    }
    $value = [int]$raw
    if ($value -lt 1024 -or $value -gt 65535) {
        Write-Host ("Порт {0} вне 1024-65535. Взят {1}." -f $value, $Default)
        return $Default
    }
    if ($value -eq $XrayPort) {
        Write-Host ("Порт {0} занят каналом xray. Взят {1}." -f $value, $Default)
        return $Default
    }
    return $value
}

$FacadePort = Get-FacadePort -Default $FacadeDefaultPort -XrayPort $XrayPort
$LogDir = Join-Path $env:TEMP 'opencode'
$GeminiHints = @(
    "$env:LOCALAPPDATA\Google\Gemini\Gemini.exe",
    "$env:LOCALAPPDATA\Programs\Gemini\Gemini.exe"
)

function Say($m) { Write-Host $m }

function PortListening([int]$port) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
}

# --- 1. Находим Gemini ----------------------------------------------------
$Gemini = $null
foreach ($hint in $GeminiHints) {
    if (Test-Path $hint) { $Gemini = $hint; break }
}
if (-not $Gemini) {
    Say "Gemini не найден. Ожидался: $env:LOCALAPPDATA\Google\Gemini\Gemini.exe"
    Say "Ничего не меняю, выход."
    exit 1
}
Say "Gemini найден: $Gemini"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# --- 2. Xray: свой канал на 10900 ----------------------------------------
if (PortListening $XrayPort) {
    Say "Xray уже слушает $XrayPort — не трогаю."
} else {
    Say "Запускаю свой Xray на $XrayPort (это может занять до двух минут)..."
    Start-Process -FilePath 'python' `
        -ArgumentList 'xray_runner.py', '--once', '--port', $XrayPort, '--subscriptions', 'subscriptions.txt' `
        -WorkingDirectory $Here -WindowStyle Hidden | Out-Null
    $waited = 0
    while (-not (PortListening $XrayPort) -and $waited -lt 150) {
        Start-Sleep -Seconds 2
        $waited += 2
    }
    if (PortListening $XrayPort) { Say "Xray поднялся за $waited с." }
    else { Say "Xray не поднялся за 150 с. Пробую всё равно — может, хватит публичных узлов." }
}

# --- 3. Фасад: переводчик на порту из настроек -------------------------------
$Pool = Join-Path $Here 'public_socks5.local.txt'
if (-not (Test-Path $Pool)) { $Pool = Join-Path $Here 'public_socks5.txt' }
$FacadeLog = Join-Path $LogDir 'facade-gemini.out.log'

if (PortListening $FacadePort) {
    Say "Фасад уже слушает $FacadePort — не трогаю."
} else {
    Say "Запускаю фасад на $FacadePort (пул: $(Split-Path -Leaf $Pool))..."
    $args = @(
        'http_facade.py',
        '--listen-host', '127.0.0.1',
        '--listen-port', "$FacadePort",
        '--nodes-file', $Pool,
        '--v2ray-socks', "socks5://127.0.0.1:$XrayPort",
        '--console-echo',
        '--log-file', $FacadeLog
    )
    Start-Process -FilePath 'python' -ArgumentList $args -WorkingDirectory $Here -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 5
    if (PortListening $FacadePort) { Say "Фасад поднялся." }
    else { Say "Фасад не поднялся — Gemini запущу всё равно, но без него." }
}

# --- 4. Закрываем старый Gemini: у уже открытого окна нет ключей ---------
$running = Get-Process -Name 'Gemini' -ErrorAction SilentlyContinue
if ($running) {
    Say "Закрываю уже открытый Gemini (иначе ключи не применятся)..."
    $running | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
}

# --- 5. Запуск Gemini через фасад -----------------------------------------
if (PortListening $FacadePort) {
    Say "Запускаю Gemini через 127.0.0.1:$FacadePort"
    Start-Process -FilePath $Gemini `
        -ArgumentList "--proxy-server=http://127.0.0.1:$FacadePort", '--disable-quic' | Out-Null
} else {
    Say "Запускаю Gemini без обхода (фасад не поднялся)."
    Start-Process -FilePath $Gemini | Out-Null
}

Say ''
Say 'Готово. Если окно Gemini открылось и сеть работает — обход живой.'
Say "Лог фасада: $FacadeLog"
Say 'Откат: закрой Gemini и запусти его обычным ярлыком без обхода.'
