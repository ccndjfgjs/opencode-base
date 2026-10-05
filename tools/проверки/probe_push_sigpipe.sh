#!/bin/sh
# Проверяет гипотезу про SIGPIPE в pre-push.
#
# Гипотеза: при `git push | head -10` канал закрывается после 10 строк,
# хук получает SIGPIPE и умирает ДО своего `exit 1`. Git for Windows
# считает умерший хук успехом — и коммит уходит.
#
# Доказательство, которого не было: тот же хук, тот же пробный пуш,
# но с настоящим удалённым и без `head`. Если код 1 — хук работает,
# и виноват именно `head`. Если код 0 — хук не работает вовсе.
#
# Всё в пробном репозитории. Настоящий origin не трогается: пуш идёт
# в пустую локальную папку, которую скрипт сам создаёт и сам удаляет.
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
# Скрипт лежит в tools/проверки, значит папка программы — на два уровня выше.
PROG="$(cd "$HERE/../.." && pwd)"
REAL_HOOK="$HERE/pre-push"

if [ ! -f "$REAL_HOOK" ]; then
    echo "ПРЕДУСЛОВИЕ НЕ ВЫПОЛНЕНО: хук не найден: $REAL_HOOK"
    echo "Ничего не пробую: проверка без исходного хука бессмысленна."
    exit 2
fi

BASE="${1:-/tmp/push-probe}"
rm -rf "$BASE"
mkdir -p "$BASE/remote" "$BASE/work"

# Пробный «удалённый» — обычная папка. Настоящий origin не участвует.
git init --bare -q "$BASE/remote/empty.git"

echo "=== 1. прямой пуш без head, хук на месте ==="
git init -q -b main "$BASE/work/repo"
cd "$BASE/work/repo"
git config user.email t@t; git config user.name t
# Файл нужен, чтобы коммит был непустым: без него `git commit` не создаётся,
# и пуш падает с «does not match any ref». Такая ошибка тоже даёт код 1,
# и её легко принять за отказ хука — первая версия пробы именно так
# и обманула: код был 1, но это был пуш, а не хук.
echo "проба" > проба.txt
cp "$REAL_HOOK" .git/hooks/pre-push
chmod +x .git/hooks/pre-push
echo "хук скопирован: $([ -f .git/hooks/pre-push ] && echo да || echo НЕТ)"
git add -A
git commit -q -m "пробный коммит"
echo "ветка: $(git rev-parse --abbrev-ref HEAD), коммитов: $(git rev-list --count HEAD)"
git remote add origin "$BASE/remote/empty.git"
set +e
git push origin main 2>"$BASE/direct.err"
DIRECT=$?
set -e
echo "  код возврата: $DIRECT (ждём 1 — хук обязан отказать)"
echo "  хук отказал: $(grep -q 'ОТКАЗ\|ALLOW_PUSH' "$BASE/direct.err" && echo да || echo НЕТ)"
echo "  коммит в пробном удалённом: $(git --git-dir="$BASE/remote/empty.git" rev-list --all --count 2>/dev/null || echo 0)"

echo
echo "=== 2. тот же пуш через | head -10 ==="
cd "$BASE/work/repo"
set +e
git push origin main 2>&1 | head -10 > "$BASE/head.out"
HEAD_CODE=${PIPESTATUS:-$?}
set -e
echo "--- что напечатало (${PIPESTATUS:-?} строк):"
while IFS= read -r line; do echo "  | $line"; done < "$BASE/head.out"
# В sh нет PIPESTATUS. Код пуша берём отдельно и честно: повторяем без head.
set +e
git push origin main >"$BASE/head2.out" 2>&1
NOCODE=$?
set -e
echo "  код без head: $NOCODE"
echo "  коммит в пробном удалённом после этого: $(git --git-dir="$BASE/remote/empty.git" rev-list --all --count 2>/dev/null || echo 0)"

echo
echo "=== 3. сколько строк печатает хук ==="
NLINES=$(wc -l < "$BASE/direct.err")
echo "  при прямом пуше хук напечатал: $NLINES строк"

echo
echo "=== 4. ВОТ ЭТОТ ТЕСТ: пуш с 2>&1 | head -10 ==="
# Ровно та команда, что в 02:55 ушла мимо хука. Смотрим не только код,
# но и ушёл ли коммит: код 0 при ушедшем коммите — это тот самый случай.
cd "$BASE/work/repo"
COMMITS_BEFORE=$(git --git-dir="$BASE/remote/empty.git" rev-list --all --count 2>/dev/null || echo 0)
set +e
git push origin main 2>&1 | head -10 > "$BASE/head3.out"
set -e
COMMITS_AFTER=$(git --git-dir="$BASE/remote/empty.git" rev-list --all --count 2>/dev/null || echo 0)
echo "--- что напечатало:"
while IFS= read -r line; do echo "  | $line"; done < "$BASE/head3.out"
echo "  код пуша (ожидаем 1): ${HEAD_CODE_FROM_PIPE:-не измерен}"
echo "  коммитов в удалённом до: $COMMITS_BEFORE, после: $COMMITS_AFTER"
if [ "$COMMITS_AFTER" = "$COMMITS_BEFORE" ]; then
    PIPE_OK=1
    echo "  ВЕРДИКТ: коммит НЕ ушёл. head обрезал вывод, но отказ устоял."
else
    PIPE_OK=0
    echo "  ВЕРДИКТ: КОМИТ УШЁЛ. head обошёл отказ — дыра не закрыта."
fi

echo
echo "=== 5. КОНТРОЛЬ: тот же тест со СТАРЫМ хуком ==="
# Пока не сравним со старым хуком, пункт 4 ничего не доказывает: вдруг
# коммит не ушёл всегда, а укрепление ни при чём. Старый хук берём из
# второй копии, которую скрипт принимает вторым аргументом.
OLD_HOOK="${2:-}"
if [ -z "$OLD_HOOK" ] || [ ! -f "$OLD_HOOK" ]; then
    echo "  старый хук не передан вторым аргументом — контроль не выполнен"
    echo "  ВЫВОД НЕДЕЙСТВИТЕЛЕН: нечем сравнить."
    OLD_OK=0
else
    rm -rf "$BASE/work/old"
    git init -q -b main "$BASE/work/old"
    cd "$BASE/work/old"
    git config user.email t@t; git config user.name t
    echo "проба" > проба.txt
    cp "$OLD_HOOK" .git/hooks/pre-push
    chmod +x .git/hooks/pre-push
    git add -A; git commit -q -m "пробный коммит"
    git remote add origin "$BASE/remote/old.git"
    git init -q --bare "$BASE/remote/old.git"
    echo "  в старом хуке trap: $(grep -c "trap '' PIPE" .git/hooks/pre-push || true)"
    echo "  в старом хуке '|| true': $(grep -c '|| true' .git/hooks/pre-push || true)"
    set +e
    git push origin main 2>&1 | head -10 > "$BASE/old.out"
    set -e
    OLD_COMMITS=$(git --git-dir="$BASE/remote/old.git" rev-list --all --count 2>/dev/null || echo 0)
    echo "  коммитов в удалённом после | head -10: $OLD_COMMITS"
    if [ "$OLD_COMMITS" != "0" ]; then
        echo "  ВЕРДИКТ КОНТРОЛЯ: СТАРЫЙ ХУК ПРОПУСТИЛ ОТПРАВКУ — дыра подтверждена."
        OLD_OK=1
    else
        echo "  ВЕРДИКТ КОНТРОЛЯ: старый хук тоже отказал."
        OLD_OK=0
    fi
fi

echo
echo "=== ИТОГ ==="
if [ "$PIPE_OK" = "1" ] && [ "$OLD_OK" = "1" ]; then
    echo "  ДЫРА ЗАКРЫТА: старый хук пропускал, новый не пропускает."
elif [ "$PIPE_OK" = "1" ] && [ "$OLD_OK" = "0" ]; then
    echo "  ОТКАЗ УСТОЯЛ И РАНЬШЕ — значит причина 02:55 не в SIGPIPE."
    echo "  Укрепление безвредно, но настоящую причину надо искать дальше."
else
    echo "  УКРЕПЛЕНИЕ НЕ ПОМОГЛО — отказ всё ещё пропускает."
fi

echo
echo "=== ВЫВОД ==="
if [ "$DIRECT" = "1" ] && [ "$NLINES" -gt 10 ]; then
    echo "  хук отказывает и печатает больше 10 строк (у нас $NLINES)"
    echo "  значит head -10 действительно обрывал канал — и трап с || true"
    echo "  это пережил. Ключевой факт — вердикт в пункте 4."
else
    echo "  структура неожиданна: прямой код $DIRECT, строк $NLINES"
fi

rm -rf "$BASE"
echo
echo "  пробный репозиторий удалён. Настоящий origin не трогался."