#!/usr/bin/env node
// ============================================================
//  Развёртывание локальной базы OpenCode_Base на любом компьютере.
//
//  Что делает:
//   1. проверяет, что база на месте и цела;
//   2. проверяет Node.js и наличие OpenCode;
//   3. раскладывает конфиг OpenCode в ~/.config/opencode/;
//   4. подставляет актуальные пути вместо старых (база может лежать где угодно);
//   5. импортирует плагин памяти и скиллы;
//   6. ставит зависимости плагина из локальной копии — интернет не нужен.
//
//  Запуск:  node tools/deploy.js [целевая_папка_конфига] [/y]
//  Обычно вызывается батником «База.bat» (главное меню, пункт 1).
// ============================================================

const fs = require("node:fs")
const path = require("node:path")
const { spawnSync } = require("node:child_process")

// ---------- пути ----------
const BASE = path.resolve(__dirname, "..")
const HOME = process.env.USERPROFILE || process.env.HOME || ""
const DEFAULT_CONFIG = path.join(HOME, ".config", "opencode")

// Рабочий стол: на разных компьютерах он может лежать в разных местах
// (обычный, в OneDrive или с локализованным именем).
function detectDesktop() {
  const candidates = [
    path.join(HOME, "Desktop"),
    path.join(HOME, "OneDrive", "Desktop"),
    path.join(HOME, "OneDrive", "Рабочий стол"),
    path.join(HOME, "Рабочий стол"),
  ]
  for (const c of candidates) if (fs.existsSync(c)) return c
  return path.join(HOME, "Desktop")
}
const DESKTOP = detectDesktop()

// ---------- аргументы ----------
const argv = process.argv.slice(2)
const NO_ASK = argv.some((a) => a.toLowerCase() === "/y")
const dstArg = argv.find((a) => !a.startsWith("/"))
const CONFIG = dstArg ? path.resolve(dstArg) : DEFAULT_CONFIG

// ---------- вывод ----------
const line = "=".repeat(60)
const out = (s = "") => console.log(s)
const step = (n, total, s) => out(`[${n}/${total}] ${s}`)
const ok = (s) => out(`        ОК: ${s}`)
const warn = (s) => out(`        ВНИМАНИЕ: ${s}`)
const fail = (s) => out(`        ОШИБКА: ${s}`)

let problems = 0
let warnings = 0

// ---------- утилиты ----------
const posix = (p) => String(p).replace(/\\/g, "/")
const win = (p) => String(p).replace(/\//g, "\\")
const exists = (p) => {
  try {
    return fs.existsSync(p)
  } catch {
    return false
  }
}
const isDir = (p) => {
  try {
    return fs.statSync(p).isDirectory()
  } catch {
    return false
  }
}
const listDirs = (p) => {
  try {
    return fs.readdirSync(p, { withFileTypes: true }).filter((e) => e.isDirectory()).map((e) => e.name)
  } catch {
    return []
  }
}
const copyDir = (src, dst) => {
  fs.mkdirSync(dst, { recursive: true })
  fs.cpSync(src, dst, { recursive: true, force: true })
}

// Пути к базе в файлах выглядят по-разному (прямые и обратные слэши),
// поэтому ищем любой путь, который заканчивается на OpenCode_Base,
// отдельно — пути к рабочему столу и к папке конфига пользователя.
const BASE_RE = /[A-Za-z]:[\\/](?:[^\\/:*?"<>|\r\n]+[\\/])*OpenCode_Base/g
const DESKTOP_RE = /[A-Za-z]:[\\/]Users[\\/][^\\/:*?"<>|\r\n]+[\\/]Desktop/g
const CONFIG_RE = /[A-Za-z]:[\\/]Users[\\/][^\\/:*?"<>|\r\n]+[\\/]\.config[\\/]opencode/gi
const TEXT_EXT = new Set([".md", ".json", ".jsonc", ".js", ".mjs", ".cjs", ".txt", ".yml", ".yaml"])

function substitute(text) {
  let n = 0
  let res = text.replace(BASE_RE, (m) => {
    n++
    return m.includes("/") ? posix(BASE) : win(BASE)
  })
  res = res.replace(DESKTOP_RE, (m) => {
    n++
    return m.includes("/") ? posix(DESKTOP) : win(DESKTOP)
  })
  res = res.replace(CONFIG_RE, (m) => {
    n++
    return m.includes("/") ? posix(CONFIG) : win(CONFIG)
  })
  return { text: res, changes: n }
}

// Замена путей в одном файле (только текстовые, только UTF-8).
// Возвращает число реальных замен: если содержимое не изменилось — 0.
function fixFile(file) {
  try {
    const ext = path.extname(file).toLowerCase()
    if (!TEXT_EXT.has(ext)) return 0
    const before = fs.readFileSync(file, "utf8")
    const { text, changes } = substitute(before)
    if (changes === 0 || text === before) return 0
    fs.writeFileSync(file, text, "utf8")
    return changes
  } catch {
    return 0
  }
}

// Обход дерева с исключениями
function walk(dir, cb, skip = ["node_modules", ".git", "_previous-version"]) {
  let entries = []
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true })
  } catch {
    return
  }
  for (const e of entries) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) {
      if (skip.includes(e.name)) continue
      walk(p, cb, skip)
    } else {
      cb(p)
    }
  }
}

// ---------- начало ----------
out()
out(line)
out("   РАЗВЁРТЫВАНИЕ БАЗЫ OpenCode_Base")
out(line)
out(`   База:   ${BASE}`)
out(`   Конфиг: ${CONFIG}`)
out()

// ---------- ШАГ 1: база на месте ----------
const TOTAL = 7
step(1, TOTAL, "Проверка базы...")
const needBase = ["profile.md", "facts.md", "projects.md"]
const missingBase = needBase.filter((f) => !exists(path.join(BASE, f)))
const confSrc = path.join(BASE, "config")
if (!exists(path.join(confSrc, "opencode.jsonc"))) missingBase.push("config\\opencode.jsonc")
if (!exists(path.join(confSrc, "plugins", "memory-base.js"))) missingBase.push("config\\plugins\\memory-base.js")
if (missingBase.length) {
  fail(`в базе не хватает файлов: ${missingBase.join(", ")}`)
  out("        Проверьте, что батник запускается из папки OpenCode_Base.")
  problems++
}
const skillsSrc = path.join(BASE, "skills")
const skillsList = listDirs(skillsSrc).filter((n) => exists(path.join(skillsSrc, n, "SKILL.md")))
if (!problems) ok(`база на месте, скиллов в базе: ${skillsList.length}`)

if (problems) {
  out()
  out(line)
  out("   РАЗВЁРТЫВАНИЕ ОСТАНОВЛЕНО — база не найдена или повреждена")
  out(line)
  process.exit(1)
}

// предупреждение о ненадёжном месте
const lower = posix(BASE).toLowerCase()
if (lower.includes("/downloads/") || lower.includes("/temp/") || lower.includes("/tmp/")) {
  warn("база лежит в папке загрузок или временной папке")
  out("                  её могут удалить. Лучше перенести базу в постоянное")
  out("                  место (например, на рабочий стол) и запустить батник снова.")
  warnings++
}

// ---------- ШАГ 2: Node.js ----------
step(2, TOTAL, "Проверка Node.js...")
const nodeVer = process.versions.node
const [nMaj, nMin] = nodeVer.split(".").map(Number)
if (nMaj > 22 || (nMaj === 22 && nMin >= 5)) {
  ok(`Node.js ${nodeVer}`)
} else {
  warn(`Node.js ${nodeVer} старее 22.5 — плагин памяти может не заработать`)
  warnings++
}

// ---------- ШАГ 3: OpenCode ----------
step(3, TOTAL, "Проверка OpenCode...")
let opencodeVer = ""
const oc = spawnSync("opencode", ["--version"], { encoding: "utf8", shell: true })
if (oc.status === 0 && oc.stdout) opencodeVer = String(oc.stdout).trim().split("\n")[0].trim()
if (opencodeVer) {
  ok(`OpenCode ${opencodeVer}`)
} else if (exists(path.join(HOME, ".local", "share", "opencode"))) {
  ok("OpenCode найден (папка данных на месте)")
} else {
  warn("OpenCode не найден в системе")
  out("                  база будет развёрнута, но запускать её будет нечем.")
  out("                  Установите OpenCode и запустите батник снова.")
  warnings++
}

// ---------- ШАГ 4: подготовка папки конфига ----------
step(4, TOTAL, "Подготовка папки конфига...")
try {
  fs.mkdirSync(CONFIG, { recursive: true })
} catch (e) {
  fail(`не удалось создать папку ${CONFIG}`)
  problems++
}
if (!problems) ok(`папка готова: ${CONFIG}`)

// снимок прежней конфигурации
if (!problems && exists(path.join(CONFIG, "opencode.jsonc"))) {
  const snap = path.join(CONFIG, "_previous-version")
  try {
    fs.rmSync(snap, { recursive: true, force: true })
    fs.mkdirSync(snap, { recursive: true })
    for (const f of ["opencode.jsonc", "AGENTS.md", "package.json", "package-lock.json"]) {
      if (exists(path.join(CONFIG, f))) fs.copyFileSync(path.join(CONFIG, f), path.join(snap, f))
    }
    for (const d of ["plugins", "command"]) {
      if (isDir(path.join(CONFIG, d))) copyDir(path.join(CONFIG, d), path.join(snap, d))
    }
    ok(`прежняя конфигурация сохранена: ${snap}`)
  } catch {
    warn("не удалось сохранить снимок прежней конфигурации")
    warnings++
  }
}

// ---------- ШАГ 5: конфиг-файлы ----------
step(5, TOTAL, "Копирование конфигурации OpenCode...")
const filesToCopy = ["AGENTS.md", "package.json", "package-lock.json", ".gitignore"]
let copied = 0
for (const f of filesToCopy) {
  const src = path.join(confSrc, f)
  if (!exists(src)) continue
  try {
    fs.copyFileSync(src, path.join(CONFIG, f))
    copied++
  } catch {
    fail(`не удалось скопировать ${f}`)
    problems++
  }
}
for (const d of ["plugins", "command"]) {
  const src = path.join(confSrc, d)
  if (!isDir(src)) continue
  try {
    copyDir(src, path.join(CONFIG, d))
    copied++
  } catch {
    fail(`не удалось скопировать папку ${d}`)
    problems++
  }
}
const cmdCount = fs.existsSync(path.join(CONFIG, "command"))
  ? fs.readdirSync(path.join(CONFIG, "command")).filter((f) => f.endsWith(".md")).length
  : 0
if (!problems) ok(`файлов и папок скопировано: ${copied}, команд: ${cmdCount}`)

// ---------- ШАГ 6: пути, конфиг, указатель, скиллы ----------
step(6, TOTAL, "Настройка путей, плагина и скиллов...")

// 6.1 главный конфиг — генерируем заново, чтобы пути были верными
const jsonc = `{
  "$schema": "https://opencode.ai/config.json",
  // Локальная база памяти пользователя — автоматически загружается
  // в КАЖДУЮ сессию (все модели, CLI и десктоп), без ручных действий.
  "instructions": [
    "${posix(BASE)}/profile.md",
    "${posix(BASE)}/projects.md",
    "${posix(BASE)}/facts.md",
    "${posix(BASE)}/библиотека/АКТИВНАЯ-ПАМЯТЬ.md"
  ]
}
`
try {
  fs.writeFileSync(path.join(CONFIG, "opencode.jsonc"), jsonc, "utf8")
  ok("opencode.jsonc настроен на текущую папку базы")
} catch {
  fail("не удалось записать opencode.jsonc")
  problems++
}

// 6.2 указатель для плагина: где лежит база
try {
  fs.writeFileSync(path.join(CONFIG, "memory-base-path.txt"), posix(BASE) + "\n", "utf8")
  ok("плагину сообщён путь к базе")
} catch {
  fail("не удалось записать memory-base-path.txt")
  problems++
}

// 6.3 замена старых путей в конфиге
let fixedFiles = 0
let fixedHits = 0
for (const rel of ["AGENTS.md"]) {
  const f = path.join(CONFIG, rel)
  if (!exists(f)) continue
  const n = fixFile(f)
  if (n) {
    fixedFiles++
    fixedHits += n
  }
}
walk(path.join(CONFIG, "command"), (f) => {
  const n = fixFile(f)
  if (n) {
    fixedFiles++
    fixedHits += n
  }
})
ok(`пути в конфиге: файлов исправлено ${fixedFiles}, замен ${fixedHits}`)

// 6.4 замена старых путей в самой базе (чтобы файлы не ссылались на чужой компьютер)
let baseFiles = 0
let baseHits = 0
for (const f of ["profile.md", "projects.md", "facts.md", "ОБРАЗЕЦ-БАЗЫ.md"]) {
  const p = path.join(BASE, f)
  if (!exists(p)) continue
  const n = fixFile(p)
  if (n) {
    baseFiles++
    baseHits += n
  }
}
for (const sub of ["projects", "sessions", "skills", "tools", "config", "инструкции", "знания", "библиотека"]) {
  const d = path.join(BASE, sub)
  if (!isDir(d)) continue
  walk(d, (f) => {
    const n = fixFile(f)
    if (n) {
      baseFiles++
      baseHits += n
    }
  })
}
ok(`пути в базе: файлов исправлено ${baseFiles}, замен ${baseHits}`)

// 6.5 импорт скиллов
const skillsDst = path.join(CONFIG, "skills")
let skillsCopied = 0
if (skillsList.length) {
  try {
    fs.mkdirSync(skillsDst, { recursive: true })
    for (const name of skillsList) {
      copyDir(path.join(skillsSrc, name), path.join(skillsDst, name))
      skillsCopied++
    }
    ok(`скиллов импортировано: ${skillsCopied}`)
  } catch {
    fail("не удалось скопировать скиллы")
    problems++
  }
} else {
  warn("в базе нет скиллов (папка skills пуста)")
  warnings++
}

// ---------- ШАГ 7: зависимости ----------
step(7, TOTAL, "Зависимости плагина @opencode-ai/plugin...")
const nmSrc = path.join(BASE, "config", "node_modules")
const nmDst = path.join(CONFIG, "node_modules")
const pluginPkg = path.join(nmDst, "@opencode-ai", "plugin", "package.json")

if (exists(path.join(nmSrc, "@opencode-ai", "plugin", "package.json"))) {
  out("        Способ: локальная копия, интернет не нужен")
  try {
    copyDir(nmSrc, nmDst)
    ok("зависимости восстановлены из копии")
  } catch {
    fail("не удалось скопировать node_modules")
    problems++
  }
} else if (exists(pluginPkg)) {
  ok("зависимости уже стоят на месте")
} else {
  out("        Способ: npm (локальной копии нет)")
  const npm = spawnSync("npm", ["install", "--offline", "--no-audit", "--no-fund"], {
    cwd: CONFIG,
    encoding: "utf8",
    shell: true,
  })
  if (npm.status !== 0) {
    const npm2 = spawnSync("npm", ["install", "--no-audit", "--no-fund"], {
      cwd: CONFIG,
      encoding: "utf8",
      shell: true,
    })
    if (npm2.status !== 0) {
      fail("установить зависимости не удалось")
      problems++
    }
  }
  if (exists(pluginPkg)) ok("зависимости установлены через npm")
  else {
    fail("зависимости не установлены")
    problems++
  }
}

// ---------- итог ----------
let pluginVer = ""
try {
  pluginVer = JSON.parse(fs.readFileSync(pluginPkg, "utf8")).version
} catch {}

out()
out(line)
if (problems) out(`   РАЗВЁРНУТО С ОШИБКАМИ: ${problems}`)
else if (warnings) out(`   ГОТОВО (с замечаниями: ${warnings})`)
else out("   ГОТОВО: база развёрнута, OpenCode настроен")
out(line)
out(`   База:        ${BASE}`)
out(`   Конфиг:      ${CONFIG}`)
out(`   Скиллы:      ${skillsCopied}`)
out(`   Плагин:      ${pluginVer || "не определён"}`)
out(`   Node.js:     ${nodeVer}`)
out(`   OpenCode:    ${opencodeVer || "не найден в PATH"}`)
if (exists(path.join(CONFIG, "_previous-version")))
  out(`   Прежняя конфигурация: ${path.join(CONFIG, "_previous-version")}`)
out()
out("   Что дальше:")
out("   1. Запустите opencode — он прочитает базу памяти, подключит плагин")
out("      и инструменты memory_save / memory_read / memory_search.")
out("   2. Папку базы не перемещайте. Если перенесёте — запустите этот батник снова.")
out(line)
out()

process.exit(problems ? 1 : 0)
