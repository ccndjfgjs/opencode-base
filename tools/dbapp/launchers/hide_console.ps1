# Прячет окно консоли, из которой запущен сам лаунчер.
#
# Зачем это отдельным файлом, а не строкой в .cmd. Внутри одной строки
# cmd кавычки не переживают: проверено, MemberDefinition с
# [DllImport("user32.dll")] в таком виде не компилируется. Здесь файл
# запускается через -File, поэтому cmd ничего не разбирает, а строка с
# кавычками живёт внутри файла.
#
# Почему не через [Console]::WindowHandle. Проверено: скрипт так ничего
# не прячет. У PowerShell своя консоль, и WindowHandle указывает на неё,
# а не на окно вызывающего cmd. Проверено и второе: окно консоли
# принадлежит conhost.exe, а не cmd.exe — поэтому у процессов cmd
# MainWindowHandle всегда был нулём, и искать надо не по процессам cmd,
# а по самим окнам.
#
# Поэтому окно ищется по имени. Лаунчер перед вызовом ставит окну
# уникальное имя (см. переменную TITLE в .cmd), и мы прячем ровно одно
# окно — своё. Чужие консоли человека не трогаются: они ищутся по
# точному совпадению имени, а не «все окна консоли подряд».
#
# Показать обратно нечем: cmd не умеет показывать своё окно. Поэтому при
# ошибке запуска лаунчер пишет причину в файл и открывает его в
# блокноте — консоль для этого не требуется.

param([string]$Marker = "")

$ErrorActionPreference = "Stop"
try {
    # Здесь только то, чем скрываем. Перечисление окон живёт в
    # классе Finder ниже: EnumWindows требует объявленный делегат,
    # и без него Add-Type не компилируется — на этом файл вставал
    # целиком, а молчащий try/catch прятал причину.
    $def = @'
[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
'@
    Add-Type -Namespace OpenCodeBase -Name Window -MemberDefinition $def -Language CSharp

    Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
namespace OpenCodeBase {
    public class Finder {
        public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
        [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc f, IntPtr p);
        [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hWnd);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        static extern int GetWindowTextW(IntPtr hWnd, StringBuilder s, int n);
        public static IntPtr Find(string marker) {
            IntPtr found = IntPtr.Zero;
            EnumWindows(delegate(IntPtr h, IntPtr p) {
                if (!IsWindowVisible(h)) return true;
                var sb = new StringBuilder(512);
                if (GetWindowTextW(h, sb, 512) <= 0) return true;
                // Заголовок консоли приходит С ХВОСТОВЫМ ПРОБЕЛОМ — измерено:
                // окно называлось ровно "OCB-MARKER-123 ". Строгое
                // сравнение строк на этом молча не срабатывало.
                var title = sb.ToString().Trim();
                if (title.StartsWith(marker, StringComparison.OrdinalIgnoreCase)) {
                    found = h; return false;
                }
                return true;
            }, IntPtr.Zero);
            return found;
        }
    }
}
'@

    $hwnd = [OpenCodeBase.Finder]::Find($Marker)
    if ($hwnd -ne [IntPtr]::Zero) {
        [OpenCodeBase.Window]::ShowWindow($hwnd, 0)
    }
} catch {
    # Спрятать не вышло — молча продолжаем: программа всё равно должна
    # запуститься, а лишнее окно консоли лучше отказа запуска.
    exit 0
}
exit 0