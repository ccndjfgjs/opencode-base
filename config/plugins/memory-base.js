import { promises as fs } from "node:fs"
import {
  appendFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
} from "node:fs"
import path from "node:path"
import { randomBytes } from "node:crypto"

// Локальная база памяти пользователя: синхронизация скиллов и уход за
// библиотекой NCP. Инструментов здесь нет и быть не должно.
//
// Почему инструментов нет. С версии opencode 1.18 плагин обязан
// отдавать объект {id, setup} — новая схема v2. Старая форма, функция с
// хуками и двенадцатью инструментами, отвергается целиком: opencode
// зовёт функцию, потом проверяет результат по схеме и не регистрирует
// его. Побочные эффекты к тому времени уже произошли, поэтому скиллы
// копировались, а инструменты memory_* и library_* не существовали.
// Инструменты переехали в мост NCP: это обычный сервер MCP, новая
// версия opencode его не касается. См. tools/ncp-bridge/memory_tools.py.

const HOME_DIR = process.env.USERPROFILE || process.env.HOME || ""
const CONFIG_DIR = HOME_DIR ? path.join(HOME_DIR, ".config", "opencode") : ""
const MARKER = CONFIG_DIR ? path.join(CONFIG_DIR, "memory-base-path.txt") : ""
const SETTINGS_FILE = CONFIG_DIR ? path.join(CONFIG_DIR, "opencode.jsonc") : ""
const DEFAULT_BASE_NAME = "OpenCode_Base"

function looksLikeBase(p) {
  if (!p) return false
  try {
    return existsSync(path.join(p, "profile.md")) || existsSync(path.join(p, "facts.md"))
  } catch {
    return false
  }
}

function tidyPath(value) {
  return String(value || "").trim().replace(/^"|"$/g, "").replace(/[\\/]+$/, "")
}

function baseFromMarker() {
  if (!MARKER) return ""
  try {
    return tidyPath(readFileSync(MARKER, "utf8"))
  } catch {
    return ""
  }
}

// Настройки знают путь к базе: он перечислен в списке instructions.
function baseFromSettings() {
  if (!SETTINGS_FILE) return ""
  try {
    const text = readFileSync(SETTINGS_FILE, "utf8")
    const found = text.match(/"[^"]*[\\/](?:profile|facts)\.md"/i)
    if (!found) return ""
    const file = found[0].slice(1, -1).replace(/\\/g, "/")
    return tidyPath(file.slice(0, file.lastIndexOf("/")))
  } catch {
    return ""
  }
}

function baseNearHome() {
  if (!HOME_DIR) return ""
  const names = [DEFAULT_BASE_NAME, DEFAULT_BASE_NAME + " — копия", DEFAULT_BASE_NAME + " - копия"]
  const roots = ["Desktop", "Documents", "Downloads", ""]
  for (const root of roots) {
    for (const name of names) {
      const candidate = root ? path.join(HOME_DIR, root, name) : path.join(HOME_DIR, name)
      if (looksLikeBase(candidate)) return candidate
    }
  }
  return ""
}

function baseOnDesktop() {
  if (!HOME_DIR) return ""
  try {
    const desktop = path.join(HOME_DIR, "Desktop")
    for (const entry of readdirSync(desktop, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue
      const candidate = path.join(desktop, entry.name)
      if (looksLikeBase(candidate)) return candidate
    }
  } catch {}
  return ""
}

// Путь ищется сам, чтобы база работала на любом компьютере и под любым
// именем пользователя. Ничьего имени в файле нет. Порядок поиска:
//   1) файл-указатель рядом с плагином: memory-base-path.txt
//   2) переменная окружения OPENCODE_MEMORY_BASE
//   3) путь из настроек opencode.jsonc (список instructions)
//   4) обычные места рядом с профилем: Рабочий стол, Документы, профиль
//   5) любая папка на Рабочем столе, похожая на базу
// Если ничего не нашлось, берётся Рабочий стол и имя базы по умолчанию.
function resolveBase() {
  const ordered = [
    baseFromMarker(),
    process.env.OPENCODE_MEMORY_BASE || "",
    baseFromSettings(),
    baseNearHome(),
    baseOnDesktop(),
  ]
  for (const candidate of ordered) {
    const clean = tidyPath(candidate)
    if (looksLikeBase(clean)) return clean.replace(/\\/g, "/")
  }
  const fallback = HOME_DIR
    ? path.join(HOME_DIR, "Desktop", DEFAULT_BASE_NAME)
    : DEFAULT_BASE_NAME
  return tidyPath(fallback).replace(/\\/g, "/")
}

const BASE = resolveBase()

// Библиотека NCP — отдельный слой долговременных знаний.
const LIBRARY = path.join(BASE, "библиотека")
const LIB_ENTRIES = path.join(LIBRARY, "записи")
const LIB_ARCHIVE = path.join(LIBRARY, "архив")
const LIB_JOURNAL = path.join(LIBRARY, "журнал")
const LIB_INDEX = path.join(LIBRARY, "index.json")
const LIB_CATALOG = path.join(LIBRARY, "КАТОГ.md")
const LIB_ACTIVE = path.join(LIBRARY, "АКТИВНАЯ-ПАМЯТЬ.md")

// Мастер-копии живут в базе; в opencode копируются недостающие и обновлённые.
// Скиллы, удалённые из базы, из opencode тоже удаляются.
const SKILLS_SRC = path.join(BASE, "skills")

const now = () => new Date().toISOString()

// Отладка плагина: ошибки и ключевые шаги пишутся сюда.
const DEBUG_LOG = path.join(BASE, "debug.log")

function debug(line) {
  try {
    appendFileSync(DEBUG_LOG, `[${now()}] ${line}\n`, "utf8")
  } catch {}
}

// ------------------------------------------------------------------- скиллы

function syncSkills() {
  try {
    if (!existsSync(SKILLS_SRC)) return
    const home = process.env.USERPROFILE || process.env.HOME
    const dst = path.join(home, ".config", "opencode", "skills")
    mkdirSync(dst, { recursive: true })

    const names = readdirSync(SKILLS_SRC, { withFileTypes: true })
      .filter((e) => e.isDirectory() && existsSync(path.join(SKILLS_SRC, e.name, "SKILL.md")))
      .map((e) => e.name)

    // Защита от стирания. Если в подключённой базе навыков нет,
    // удалять из OpenCode нечего: иначе пустая папка skills снесла бы
    // все навыки разом. Так уже случалось — навыки восстанавливали.
    if (!names.length) {
      debug(`skills: в базе «${BASE}» навыков нет — в OpenCode ничего не тронуто`)
      return
    }

    let copied = []
    for (const name of names) {
      const srcFile = path.join(SKILLS_SRC, name, "SKILL.md")
      const dstDir = path.join(dst, name)
      const dstFile = path.join(dstDir, "SKILL.md")
      let need = !existsSync(dstFile)
      if (!need) need = readFileSync(srcFile, "utf8") !== readFileSync(dstFile, "utf8")
      if (need) {
        mkdirSync(dstDir, { recursive: true })
        cpSync(path.join(SKILLS_SRC, name), dstDir, { recursive: true })
        copied.push(name)
      }
    }

    // скиллы, которых больше нет в базе, — убрать из opencode
    for (const entry of readdirSync(dst, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue
      const name = entry.name.replace(/\.md$/i, "")
      if (!names.includes(name) && !names.includes(entry.name)) {
        rmSync(path.join(dst, entry.name), { recursive: true, force: true })
        debug(`skill removed: ${entry.name} (нет в базе)`)
      }
    }

    if (copied.length) debug(`skills synced: ${copied.join(", ")}`)
  } catch (e) {
    debug(`syncSkills ERROR: ${e && e.stack ? e.stack : String(e)}`)
  }
}

// -------------------------------------------------------------- библиотека

function ensureLibrarySync() {
  for (const dir of [LIBRARY, LIB_ENTRIES, LIB_ARCHIVE, LIB_JOURNAL]) mkdirSync(dir, { recursive: true })
  if (!existsSync(LIB_ACTIVE)) {
    appendFileSync(
      LIB_ACTIVE,
      "# Активная память NCP\n\n- **Последняя контрольная точка:** не создана\n- **Текущая цель:** не задана\n\n## Важные решения\n\n- Пока нет.\n\n## Незавершённое\n\n- Пока нет.\n\n## Связанные записи\n\n- Пока нет.\n",
      "utf8"
    )
  }
}

function libraryRelative(file) {
  return path.relative(LIBRARY, file).replace(/\\/g, "/")
}

function walkLibraryFiles(dir, out = []) {
  if (!existsSync(dir)) return out
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name)
    if (entry.isDirectory()) walkLibraryFiles(p, out)
    else if (entry.isFile() && entry.name.toLowerCase().endsWith(".md")) out.push(p)
  }
  return out
}

function parseRecord(text) {
  const result = { meta: {}, body: String(text || "") }
  if (!result.body.startsWith("---\n")) return result
  const end = result.body.indexOf("\n---\n", 4)
  if (end < 0) return result
  const header = result.body.slice(4, end)
  for (const line of header.split("\n")) {
    const pos = line.indexOf(":")
    if (pos < 0) continue
    const key = line.slice(0, pos).trim()
    const value = line.slice(pos + 1).trim()
    if (key) result.meta[key] = value
  }
  result.body = result.body.slice(end + 5).trimStart()
  return result
}

function section(text, name) {
  const src = String(text || "")
  const marker = `## ${name}`
  const start = src.indexOf(marker)
  if (start < 0) return ""
  const from = start + marker.length
  const next = src.indexOf("\n## ", from)
  return src.slice(from, next < 0 ? undefined : next).trim()
}

function entryFromFile(file) {
  try {
    const parsed = parseRecord(readFileSync(file, "utf8"))
    if (!parsed.meta.id || !parsed.meta.title) return null
    return {
      id: parsed.meta.id,
      title: parsed.meta.title,
      type: parsed.meta.type || "note",
      topic: parsed.meta.topic || "общее",
      status: parsed.meta.status || "active",
      created: parsed.meta.created || "",
      updated: parsed.meta.updated || "",
      tags: parsed.meta.tags || "",
      source: parsed.meta.source || "",
      confidence: parsed.meta.confidence || "medium",
      supersedes: parsed.meta.supersedes || "",
      path: libraryRelative(file),
      preview: section(parsed.body, "Содержание").replace(/\s+/g, " ").slice(0, 220),
    }
  } catch {
    return null
  }
}

async function atomicWrite(file, text) {
  await fs.mkdir(path.dirname(file), { recursive: true })
  const tmp = `${file}.tmp-${process.pid}-${randomBytes(3).toString("hex")}`
  await fs.writeFile(tmp, text, "utf8")
  await fs.rename(tmp, file)
}

async function libraryLog(action, details) {
  const month = now().slice(0, 7)
  const file = path.join(LIB_JOURNAL, `${month}.md`)
  await fs.mkdir(LIB_JOURNAL, { recursive: true })
  if (!existsSync(file)) await fs.writeFile(file, `# Журнал библиотеки NCP — ${month}\n\n`, "utf8")
  await fs.appendFile(file, `- [${now()}] ${action}: ${details}\n`, "utf8")
}

async function rebuildLibraryIndex(logAction = true) {
  ensureLibrarySync()
  const files = [...walkLibraryFiles(LIB_ENTRIES), ...walkLibraryFiles(LIB_ARCHIVE)]
  const entries = files.map(entryFromFile).filter(Boolean)
  entries.sort((a, b) => String(b.updated).localeCompare(String(a.updated)))
  const topics = {}
  for (const e of entries) topics[e.topic] = (topics[e.topic] || 0) + 1
  const data = {
    schema: "ncp-library-index-v1",
    updated: now(),
    count: entries.length,
    topics,
    entries,
  }
  await atomicWrite(LIB_INDEX, JSON.stringify(data, null, 2) + "\n")

  const grouped = new Map()
  for (const e of entries) {
    if (!grouped.has(e.topic)) grouped.set(e.topic, [])
    grouped.get(e.topic).push(e)
  }
  const lines = [
    "# Каталог библиотеки NCP",
    "",
    `**Последнее обновление:** ${data.updated}  `,
    `**Записей:** ${data.count}`,
    "",
  ]
  if (!entries.length) lines.push("Записей пока нет.", "")
  for (const topic of [...grouped.keys()].sort((a, b) => a.localeCompare(b, "ru"))) {
    lines.push(`## ${topic}`, "")
    for (const e of grouped.get(topic)) {
      const tags = e.tags ? ` — теги: ${e.tags}` : ""
      lines.push(`- [${e.status}] **${e.title}** — \`${e.id}\` (${e.type})${tags}`)
    }
    lines.push("")
  }
  await atomicWrite(LIB_CATALOG, lines.join("\n"))
  if (logAction) await libraryLog("reindex", `${entries.length} записей, ${Object.keys(topics).length} тем`)
  return data
}

// ------------------------------------------------------------------ запуск

function prepareBase() {
  // Папки создаём синхронно: opencode может завершиться сразу после
  // загрузки плагинов, и недописанная асинхронная работа пропала бы.
  for (const dir of [path.join(BASE, "sessions"), path.join(BASE, "projects")]) {
    mkdirSync(dir, { recursive: true })
  }
  ensureLibrarySync()
  if (!existsSync(LIB_INDEX)) {
    // Индекс не пересобираем синхронно и не ждём: мост NCP его и так
    // чинит инструментом ncp_reindex, а здесь важно только не мешать.
    rebuildLibraryIndex(false).catch((e) =>
      debug(`rebuildLibraryIndex ERROR: ${e && e.stack ? e.stack : String(e)}`)
    )
  }
  syncSkills()
  debug(`plugin v2: база «${BASE}»`)
}

export default {
  id: "memory-base",
  setup() {
    prepareBase()
  },
}
