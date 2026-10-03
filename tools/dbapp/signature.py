# -*- coding: utf-8 -*-
"""Проверка цифровой подписи установщика через Get-AuthenticodeSignature.

Этап 4 раздела 7 плана. Модуль отвечает на один вопрос: файл подписан тем,
кем мы ожидаем, или нет.

**Что проверено живьём 03.10.2026, а не взято из памяти.**

| Что | Факт |
|---|---|
| Перечисление | `System.Management.Automation.SignatureStatus` |
| Значения | `Valid`=0, `UnknownError`=1, `NotSigned`=2, `HashMismatch`=3, `NotTrusted`=4, `NotSupportedFileFormat`=5, `Incompatible`=6 |
| Скорость | **0,28 с на файл** — сверка обязана идти в рабочем потоке, не в потоке окна |
| Имя подписанта | лежит в `SignerCertificate.Subject`, а простом виде это `CN=OpenJS Foundation` |

**Три вещи, на которых спотыкаются по незнанию.**

1. **Статус сравнивается по числу, а не по строке.** На этой машине приходит
   английское `Valid`, но локализация зависит от установки Windows, и завтра
   имя может стать другим. Число останется прежним.

2. **`NotSigned` — это ответ, а не сбой.** Сбой — когда команда не дала
   результата вовсе: например, `winget.exe` в WindowsApps не является обычным
   файлом и команда падает с `System.IO.IOException`. Такой случай обязан
   давать «проверка не выполнена», а не «подпись верна». Путать эти два
   исхода опаснее всего: первый означает «мы не знаем», второй — «всё в
   порядке».

3. **Сверять надо по полному Subject, а не по одному `CN`.** Подписантом
   `cmd.exe` является `CN=Microsoft Windows`, и имени `Microsoft Corporation`
   в `CN` нет — оно лежит в `O=` того же сертификата:
   `CN=Microsoft Windows, O=Microsoft Corporation, L=Redmond…`. Сравнение
   только по `CN` отвергло бы файлы самой Windows. Поэтому сверяется вся
   строка Subject, а `CN` остаётся только для показа.

**`HashMismatch` воспроизводится, но не на любом файле.** Правка байта внутри
`node.exe` даёт именно `HashMismatch` (3). Правка байта внутри `cmd.exe` на
трёх разных смещениях даёт `NotSigned` (2) — файлы самой Windows ведут себя
иначе. Из этого нельзя заключать, что состояние недостижимо: сначала был
сделан вывод «воспроизвести не удалось» по одному файлу, и он был неверен.

**Имя подписанта не равно издателю из winget.** `winget show` отдаёт
издателя из манифеста пакета, а подпись файла — это кто подписал сам `.exe`.
Разные вещи, и разница видна на Node.js:

| | что | |
|---|---|---|
| издатель в манифесте winget | `Node.js Foundation` | |
| кто подписал node.exe | `OpenJS Foundation` | **не совпадает** |

Поэтому в реестре два разных поля: `expected_publisher` — издатель из
каталога winget, и `expected_signer` — кто подписал файл. Сверка идёт по
второму. Сравнивать по первому значило бы отвергать настоящие установщики,
а это худший вид ошибки в проверке безопасности.

**Совпадение ищется по вхождению в ПОЛНОМ Subject, а не равенством и не по
одному `CN`.** Подписантом `cmd.exe` является `CN=Microsoft Windows`, а
`Microsoft Corporation` лежит в `O=` того же сертификата. Строгое равенство
по `CN` отвергло бы файлы самой Windows. Поэтому хранится вся строка Subject,
и ожидаемое имя ищется в ней. Ожидаемое может быть и списком через запятую —
так подписывают те, кто переименовал компанию.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Сколько ждать PowerShell. Проверка одного файла идёт около 0,3 с, но
#: первый вызов на холодную разворачивает сборку и уходил в 1,8 с. Запас
#: большой, потому что зависшая проверка хуже неверного ответа: человек
#: не поймёт, что окно замерло.
POWERSHELL_TIMEOUT = 30

#: Значения System.Management.Automation.SignatureStatus. Проверено 03.10.2026
#: запросом [enum]::GetNames. Числа, а не строки: см. предупреждение вверху.
STATUS_VALID = 0
STATUS_UNKNOWN_ERROR = 1
STATUS_NOT_SIGNED = 2
STATUS_HASH_MISMATCH = 3
STATUS_NOT_TRUSTED = 4
STATUS_NOT_SUPPORTED_FILE_FORMAT = 5
STATUS_INCOMPATIBLE = 6

STATUS_NAMES = {
    STATUS_VALID: "подпись действительна",
    STATUS_UNKNOWN_ERROR: "проверка не удалась",
    STATUS_NOT_SIGNED: "подписи нет",
    STATUS_HASH_MISMATCH: "подпись не сходится с файлом",
    STATUS_NOT_TRUSTED: "подписавшему нельзя доверять",
    STATUS_NOT_SUPPORTED_FILE_FORMAT: "формат файла не поддерживается",
    STATUS_INCOMPATIBLE: "несовместимая подпись",
}

#: Что означает каждый исход для решения «запускать ли файл». True — файл
#: можно запускать, False — нельзя. Отдельного «не знаю» здесь нет намеренно:
#: для установщика неизвестность равносильна отказу. Сама неизвестность
#: остаётся видна в checked, чтобы её можно было показать человеку отдельно.
STATUS_ALLows = {
    STATUS_VALID: True,
    STATUS_NOT_SIGNED: False,
    STATUS_HASH_MISMATCH: False,
    STATUS_NOT_TRUSTED: False,
    STATUS_NOT_SUPPORTED_FILE_FORMAT: False,
    STATUS_INCOMPATIBLE: False,
    STATUS_UNKNOWN_ERROR: False,
}


@dataclass
class SignatureResult:
    """Ответ одной проверки. Различает «не подходит» и «не смогли узнать»."""

    path: str = ""
    checked: bool = False        # ответ получен?
    status: int = STATUS_UNKNOWN_ERROR
    status_text: str = ""        # как это назвала Windows, строкой
    signer: str = ""             # CN из сертификата, только для показа
    subject: str = ""            # весь Subject, именно по нему идёт сверка
    issuer: str = ""
    expected: str = ""
    detail: str = ""

    @property
    def safe_to_run(self) -> bool:
        """Можно ли запускать файл. Неизвестность равносильна отказу.

        Для установщика это единственно разумное поведение: «мы не смогли
        узнать» и «всё в порядке» не должны выглядеть одинаково, а выглядеть
        одинаково они будут, если «не знаем» прочитать как «можно».
        """
        return bool(self.checked and STATUS_ALLows.get(self.status) is True)

    @property
    def verified(self) -> bool:
        """Подпись проверена и подписант тот, кого ждали.

        Отличать от `safe_to_run` обязательно: файл может быть подписан верно,
        но не тем, кто ожидался. Запускать его нельзя, а сказать «подпись
        плохая» тоже нельзя — она в порядке, не тот, кто нужен.
        """
        return (self.checked
                and self.status == STATUS_VALID
                and bool(self.expected)
                and signer_matches(self.subject or self.signer, self.expected))


def _tokens(value: str) -> list[str]:
    """Разбить на слова: буквы и цифры, всё прочее — разделитель.

    Сверка идёт по словам, а не по кускам строки. Причина — «CN=Adobe
    Systems» и «CN=Adobe Inc.» должны подходить под ожидание «Adobe», но
    подстрока без границ пропустила бы и «CN=Notepad Adobe Viewer» от
    постороннего издателя. Слова и есть те границы.
    """
    return [w for w in re.split(r"[^0-9A-Za-zЀ-ӿ]+", str(value or "")) if w]


def _contains_sequence(haystack: list[str], needle: list[str]) -> bool:
    """Есть ли подряд идущие слова needle внутри haystack."""
    if not needle or len(needle) > len(haystack):
        return False
    width = len(needle)
    for start in range(len(haystack) - width + 1):
        if haystack[start:start + width] == needle:
            return True
    return False


def signer_matches(subject_or_name: str, expected: str) -> bool:
    """Подошло ли имя подписанта к ожидаемому.

    Принимается полный Subject или одно имя. Сравнение идёт по словам, а не
    по одному `CN`: подписантом `cmd.exe` является `CN=Microsoft Windows`, а
    `Microsoft Corporation` лежит в `O=` того же сертификата, и сверка только
    по `CN` отвергла бы файлы самой Windows.

    Ожидаемое может быть и списком через запятую: так подписывают те, кто
    переименовал компанию, и одна строка описывает и прежнего, и нынешнего
    подписанта.
    """
    actual_tokens = _tokens(subject_or_name)
    if not actual_tokens or not expected:
        return False
    for want in str(expected).split(","):
        want_tokens = _tokens(want)
        if not want_tokens:
            continue
        if _contains_sequence(actual_tokens, want_tokens):
            return True
        # Обратный порядок встречается, когда ожидание записано короче
        # настоящего имени: «Epic Games, Inc.» против «Epic Games». Обратное
        # вхождение допускается только при заметной длине ожидания, иначе
        # короткое имя начало бы подтверждать что угодно.
        if len(want_tokens) >= 2 and _contains_sequence(want_tokens, actual_tokens):
            return True
    return False


def _run_powershell(path: Path) -> tuple[dict | None, str]:
    """Спросить у PowerShell про подпись. None — команды не было ответа.

    PowerShell вызывается отдельным процессом, а не через текущий: так его
    версия и политика выполнения не зависят от того, чем запущена программа.
    Ошибки команды не проглатываются молча — они возвращаются вторым
    значением, чтобы «не смогли узнать» не превратилось в «подпись верна».
    """
    literal = str(path).replace("'", "''")
    script = (
        "$ErrorActionPreference = 'Stop';"
        f"$s = Get-AuthenticodeSignature -FilePath '{literal}';"
        "$o = [ordered]@{ Status = [string]$s.Status; Value = [int]$s.Status;"
        " CN = ''; Subject = ''; Issuer = '' };"
        "if ($null -ne $s.SignerCertificate) {"
        "  $o.Subject = [string]$s.SignerCertificate.Subject;"
        "  $p = ($s.SignerCertificate.Subject -split ','"
        "    | Where-Object { $_ -match 'CN=' } | Select-Object -First 1);"
        "  $o.CN = ($p -replace '^\\s*CN=', '').Trim();"
        "  $o.Issuer = [string]$s.SignerCertificate.Issuer"
        "};"
        "$o | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=POWERSHELL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None, f"PowerShell не ответил за {POWERSHELL_TIMEOUT} с"
    except OSError as exc:
        return None, f"PowerShell не запустился: {exc.__class__.__name__}"
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        err = (proc.stderr or "").strip().splitlines()
        tail = err[-1][:200] if err else "без текста ошибки"
        return None, f"команда не сработала: {tail}"
    # Ответ может прийти несколькими строками, если PowerShell что-то дописал.
    last = out.splitlines()[-1]
    try:
        import json

        data = json.loads(last)
    except ValueError:
        return None, f"ответ не разобран: {last[:120]}"
    if not isinstance(data, dict) or "Value" not in data:
        return None, f"в ответе нет статуса: {last[:120]}"
    return data, ""


def check_signature(path: Path, expected: str = "") -> SignatureResult:
    """Проверить подпись файла.

    Ожидаемое имя пустым быть не должно: тогда сверять не с чем, и результат
    честно говорит «проверять нечего», а не сходит с рук. Отличать эти два
    случая обязательно — иначе вкладка напишет «подпись проверена», не
    сверив ничего.
    """
    path = Path(path)
    result = SignatureResult(path=str(path), expected=str(expected or "").strip())
    if not path.is_file():
        result.detail = "файла нет — проверять нечего"
        return result
    if not result.expected:
        result.detail = ("имя ожидаемого подписанта не задано в реестре — "
                         "проверять не с чем, и сказать «подпись верна» нельзя")
        return result

    data, error = _run_powershell(path)
    if data is None:
        # Сбой команды — это «не знаю», а не «не подходит». Путать нельзя.
        result.checked = False
        result.status = STATUS_UNKNOWN_ERROR
        result.status_text = STATUS_NAMES[STATUS_UNKNOWN_ERROR]
        result.detail = error
        return result

    try:
        result.status = int(data.get("Value"))
    except (TypeError, ValueError):
        result.detail = f"в ответе не число: {data.get('Value')!r}"
        return result
    result.checked = True
    result.status_text = str(data.get("Status") or "")
    result.signer = str(data.get("CN") or "").strip()
    result.subject = str(data.get("Subject") or "").strip()
    result.issuer = str(data.get("Issuer") or "").strip()

    if result.status != STATUS_VALID:
        result.detail = (f"{STATUS_NAMES.get(result.status, 'неизвестный статус')} "
                        f"(Windows сказала {result.status_text})")
        return result

    if not result.signer:
        result.detail = "подпись действительна, но имя подписанта получить не удалось"
        return result

    # Сверка идёт по полному Subject: у cmd.exe имя Microsoft Corporation
    # лежит в поле O=, а в поле CN там Microsoft Windows.
    if signer_matches(result.subject or result.signer, result.expected):
        result.detail = f"подпись действительна, подписал {result.signer}"
        return result

    # Самое важное сообщение в модуле: файл подписан по-настоящему, но не тем,
    # кем мы ожидали. Молчаливый отказ здесь выглядел бы как «подпись плохая».
    result.detail = (f"подпись действительна, но подписал {result.signer}, "
                     f"а ожидали {result.expected}")
    return result


def describe(result: SignatureResult) -> str:
    """Строка для показа человеку."""
    if not result.path:
        return "проверять нечего"
    if result.detail:
        return result.detail
    if result.verified:
        return f"подпись действительна, подписал {result.signer}"
    return STATUS_NAMES.get(result.status, "неизвестный статус")


def powershell_available() -> tuple[bool, str]:
    """Есть ли PowerShell. Проверяется один раз и кэшируется вызывающим."""
    try:
        proc = subprocess.run(
            ["powershell", "-NoLogo", "-NoProfile", "-Command",
             "$PSVersionTable.PSVersion.Major"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=POWERSHELL_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"запустить не удалось: {exc.__class__.__name__}"
    if proc.returncode != 0:
        return False, "PowerShell есть, но не отвечает"
    major = (proc.stdout or "").strip().splitlines()
    return True, f"PowerShell {major[0] if major else '?'}"


#: Имя издателя из манифеста winget и имя подписанта — разные вещи. Регулярка
#: используется, чтобы убрать из полного имени только CN: в Subject лежит
#: «CN=OpenJS Foundation, O=OpenJS Foundation, L=..., C=US», а нужно имя.
CN_RE = re.compile(r"(?:^|,)\s*CN\s*=\s*(?P<name>[^,]+)")


def subject_to_common_name(subject: str) -> str:
    """Из полного Subject взять только CN. На случай строк извне."""
    match = CN_RE.search(str(subject or ""))
    return match.group("name").strip() if match else ""
