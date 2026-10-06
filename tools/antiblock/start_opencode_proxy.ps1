[CmdletBinding()]
param(
    [switch]$FacadeOnly,
    [string]$OpenCodePath = "$env:LOCALAPPDATA\Programs\@opencode-aidesktop\OpenCode.exe",
    [string]$PoolFile,
    [int]$XrayPort = 10900,
    [int]$FacadeDefaultPort = 17890,
    [switch]$NoXray
)

$ErrorActionPreference = "Stop"

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

$listenHost = "127.0.0.1"
$listenPort = Get-FacadePort -Default $FacadeDefaultPort -XrayPort $XrayPort
$facadeScript = Join-Path $PSScriptRoot "http_facade.py"
if ([string]::IsNullOrWhiteSpace($PoolFile)) {
    # Живой список — появляется после обновления (кнопка "Обновить" или
    # автообновление фасада раз в сутки); пока его нет — стартовый из базы.
    $livePool = Join-Path $PSScriptRoot "public_socks5.local.txt"
    $starterPool = Join-Path $PSScriptRoot "public_socks5.txt"
    if (Test-Path -LiteralPath $livePool) {
        $PoolFile = $livePool
    } else {
        $PoolFile = $starterPool
    }
}
$PoolFile = [System.IO.Path]::GetFullPath($PoolFile)
$logSuffix = Get-Date -Format "yyyyMMddHHmmssfff"
$stdoutPath = Join-Path $env:TEMP "opencode-facade-$logSuffix.out.log"
$stderrPath = Join-Path $env:TEMP "opencode-facade-$logSuffix.err.log"

function Test-TcpPort {
    param(
        [string]$HostName,
        [int]$Port
    )
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync($HostName, $Port)
        if (-not $task.Wait(250)) {
            return $false
        }
        return $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Resolve-Python {
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    $command = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    throw "Python was not found in PATH"
}

function Stop-OwnedProcess {
    param($Process)
    if ($null -eq $Process) {
        return
    }
    try {
        $Process.Refresh()
        if (-not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force
        }
    }
    catch {
    }
}

if (-not (Test-Path -LiteralPath $facadeScript)) {
    throw "Facade script was not found: $facadeScript"
}
if (-not (Test-Path -LiteralPath $PoolFile)) {
    throw "Proxy pool file was not found: $PoolFile"
}

$python = Resolve-Python
$facadeProcess = $null
$ownsFacade = $false
$xrayProcess = $null
$ownsXray = $false
$v2raySocks = ""

# Свой Xray (V2Ray-канал): поднимаем до фасада, чтобы фасад мог
# отдать ему приоритет. Без сторонних программ: xray.exe скачивается
# сам при первом запуске (xray_runner.py), узлы — из subscriptions.txt.
if (-not $NoXray) {
    $xrayScript = Join-Path $PSScriptRoot "xray_runner.py"
    if (Test-Path -LiteralPath $xrayScript) {
        if (-not (Test-TcpPort -HostName "127.0.0.1" -Port $XrayPort)) {
            Write-Host "Поднимаю свой V2Ray-канал. Первый раз это занимает пару минут, дальше секунды..."
            $xrayLogSuffix = Get-Date -Format "yyyyMMddHHmmssfff"
            $xrayOut = Join-Path $env:TEMP "opencode-xray-$xrayLogSuffix.out.log"
            $xrayErr = Join-Path $env:TEMP "opencode-xray-$xrayLogSuffix.err.log"
            $xrayArgs = @(
                $xrayScript,
                "--once",
                "--port", "$XrayPort",
                "--subscriptions", (Join-Path $PSScriptRoot "subscriptions.txt")
            )
            try {
                $xrayProcess = Start-Process `
                    -FilePath $python `
                    -ArgumentList $xrayArgs `
                    -WorkingDirectory $PSScriptRoot `
                    -WindowStyle Hidden `
                    -RedirectStandardOutput $xrayOut `
                    -RedirectStandardError $xrayErr `
                    -PassThru
                $ownsXray = $true
                $xrayDeadline = [DateTime]::UtcNow.AddSeconds(150)
                while ([DateTime]::UtcNow -lt $xrayDeadline) {
                    $xrayProcess.Refresh()
                    if ($xrayProcess.HasExited) { break }
                    if (Test-TcpPort -HostName "127.0.0.1" -Port $XrayPort) { break }
                    Start-Sleep -Milliseconds 1000
                }
            }
            catch {
                Write-Warning ("Не удалось поднять свой Xray: {0}" -f $_.Exception.Message)
                $xrayProcess = $null
                $ownsXray = $false
            }
        }
        if (Test-TcpPort -HostName "127.0.0.1" -Port $XrayPort) {
            $v2raySocks = "socks5://127.0.0.1:{0}" -f $XrayPort
            Write-Host ("V2Ray-канал готов: {0}" -f $v2raySocks)
        }
        else {
            Write-Warning "Свой Xray не поднялся — фасад пойдёт только через публичные прокси."
        }
    }
}

if (-not (Test-TcpPort -HostName $listenHost -Port $listenPort)) {
    $facadeArguments = @(
        $facadeScript,
        "--listen-host", $listenHost,
        "--listen-port", $listenPort,
        "--nodes-file", $PoolFile,
        "--refresh-hours", "24",
        "--console-echo",
        "--log-file", $stdoutPath
    )
    if ($v2raySocks -ne "") {
        $facadeArguments += @("--v2ray-socks", $v2raySocks)
    }
    Write-Host "Запускаю фасад $proxyUrl (лог пишу и в файл, и в это окно)..."
    $facadeProcess = Start-Process `
        -FilePath $python `
        -ArgumentList $facadeArguments `
        -WorkingDirectory $PSScriptRoot `
        -NoNewWindow `
        -PassThru
    $ownsFacade = $true
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while ([DateTime]::UtcNow -lt $deadline) {
        $facadeProcess.Refresh()
        if ($facadeProcess.HasExited) {
            $details = if (Test-Path -LiteralPath $stderrPath) {
                (Get-Content -LiteralPath $stderrPath -Raw)
            } else {
                ""
            }
            throw "Facade exited with code $($facadeProcess.ExitCode). $details"
        }
        if (Test-TcpPort -HostName $listenHost -Port $listenPort) {
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not (Test-TcpPort -HostName $listenHost -Port $listenPort)) {
        Stop-OwnedProcess -Process $facadeProcess
        throw ("Facade did not open {0}:{1}" -f $listenHost, $listenPort)
    }
}
else {
    Write-Host ("Facade already listens on {0}:{1}; reusing it." -f $listenHost, $listenPort)
}

$proxyUrl = "http://{0}:{1}" -f $listenHost, $listenPort
$env:HTTP_PROXY = $proxyUrl
$env:HTTPS_PROXY = $proxyUrl
$env:http_proxy = $proxyUrl
$env:https_proxy = $proxyUrl
$env:NO_PROXY = "127.0.0.1,localhost,::1"
$env:no_proxy = "127.0.0.1,localhost,::1"
$env:PYTHONUNBUFFERED = "1"

try {
    if ($FacadeOnly) {
        Write-Host "Facade started: $proxyUrl"
        if ($v2raySocks -ne "") {
            Write-Host ("V2Ray-канал: {0} (приоритет)" -f $v2raySocks)
        }
        Write-Host "Press Ctrl+C to stop it."
        while (($null -eq $facadeProcess -or -not $facadeProcess.HasExited) -and ($null -eq $xrayProcess -or -not $xrayProcess.HasExited -or -not $ownsXray)) {
            Start-Sleep -Seconds 1
            if ($null -ne $facadeProcess) {
                $facadeProcess.Refresh()
            }
            if ($null -ne $xrayProcess) {
                $xrayProcess.Refresh()
            }
        }
    }
    else {
        if (-not (Test-Path -LiteralPath $OpenCodePath)) {
            throw "OpenCode was not found: $OpenCodePath"
        }
        $existing = @(Get-Process -Name "OpenCode" -ErrorAction SilentlyContinue)
        if ($existing.Count -gt 0) {
            # OpenCode (Electron) single-instance: новая копия молча
            # завершается, если экземпляр уже открыт. Чтобы обход
            # реально заработал, закрываем старый OpenCode и
            # запускаем его заново через прокси.
            Write-Host ("Закрываю текущий OpenCode ({0} процессов)..." -f $existing.Count)
            $existing | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
            # Ждём, пока процессы реально завершатся (Electron гасится не сразу)
            $deadline = [DateTime]::UtcNow.AddSeconds(20)
            while ([DateTime]::UtcNow -lt $deadline) {
                $left = @(Get-Process -Name "OpenCode" -ErrorAction SilentlyContinue)
                if ($left.Count -eq 0) { break }
                Start-Sleep -Milliseconds 500
            }
        }
        Write-Host "Starting OpenCode with proxy $proxyUrl"
        $openCodeProcess = Start-Process -FilePath $OpenCodePath -PassThru
        Wait-Process -Id $openCodeProcess.Id
    }
}
finally {
    if ($ownsFacade) {
        Stop-OwnedProcess -Process $facadeProcess
    }
    if ($ownsXray) {
        Stop-OwnedProcess -Process $xrayProcess
    }
}
