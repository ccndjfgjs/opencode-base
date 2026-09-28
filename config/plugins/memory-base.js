import { tool } from "@opencode-ai/plugin"
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

// Локальная база памяти пользователя.
// Путь ищется сам, чтобы база работала на любом компьютере и под любым
// именем пользователя. Ничьего имени в файле нет. Порядок поиска:
//   1) файл-указатель рядом с плагином: ~/.config/opencode/memory-base-path.txt
//   2) переменная окружения OPENCODE_MEMORY_BASE
//   3) путь из настроек opencode.jsonc (список instructions)
//   4) обычные места рядом с профилем: Рабочий стол, Документы, профиль
//   5) любая папка на Рабочем столе, похожая на базу
// Если ничего не нашлось, берётся Рабочий стол и имя базы по умолчанию.
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
const PROJECTS = path.join(BASE, "projects")
const INDEX = path.join(PROJECTS, "index.json")
const SESSIONS = path.join(BASE, "sessions")

// Библиотека NCP — отдельный слой долговременных знаний.
const LIBRARY = path.join(BASE, "библиотека")
const LIB_ENTRIES = path.join(LIBRARY, "записи")
const LIB_ARCHIVE = path.join(LIBRARY, "архив")
const LIB_JOURNAL = path.join(LIBRARY, "журнал")
const LIB_INDEX = path.join(LIBRARY, "index.json")
const LIB_CATALOG = path.join(LIBRARY, "КАТАЛОГ.md")
const LIB_ACTIVE = path.join(LIBRARY, "АКТИВНАЯ-ПАМЯТЬ.md")
const LIB_TYPES = ["fact", "note", "decision", "procedure", "source", "summary", "question"]
const LIB_STATUSES = ["active", "draft", "superseded", "archived"]
const LIB_CONFIDENCE = ["high", "medium", "low"]

// Как имя провайдера/модели показывать в базе
const PROVIDER_AI = {
  anthropic: "Claude",
  google: "Gemini",
  gemini: "Gemini",
  deepseek: "DeepSeek",
  zhipu: "GLM",
  "z-ai": "GLM",
  glm: "GLM",
  moonshot: "Kimi",
  kimi: "Kimi",
  qwen: "Qwen",
  alibaba: "Qwen",
  openai: "GPT",
  "x-ai": "Grok",
  grok: "Grok",
  mistral: "Mistral",
  yandex: "Алиса",
  alisa: "Алиса",
}

function sanitize(name) {
  return String(name).replace(/[\\/:*?"<>|]/g, "-").trim()
}

function aiName(providerID, modelID) {
  const p = (providerID || "").toLowerCase()
  if (p && PROVIDER_AI[p]) return PROVIDER_AI[p]
  // бесплатные модели opencode — показываем саму модель
  if (modelID) {
    const m = String(modelID).split("/").pop()
    return m.charAt(0).toUpperCase() + m.slice(1)
  }
  return sanitize(p || "Нейросеть") || "Нейросеть"
}

const today = () => new Date().toISOString().slice(0, 10)
const now = () => new Date().toISOString()

// отладка плагина: ошибки и ключевые шаги пишутся сюда
const DEBUG_LOG = path.join(BASE, "debug.log")
// синхронная запись: единственный await в session.idle — ctx.client.session.get,
// после него весь код синхронный, чтобы завершение процесса (opencode run)
// не могло оборвать запись журналов
function debug(line) {
  try {
    appendFileSync(DEBUG_LOG, `[${now()}] ${line}\n`, "utf8")
  } catch {}
}
const norm = (p) => decodeURI(String(p)).replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase()

async function readFileSafe(file) {
  try {
    return await fs.readFile(file, "utf8")
  } catch {
    return ""
  }
}

function readIndexSync() {
  try {
    return JSON.parse(readFileSync(INDEX, "utf8"))
  } catch {
    return {}
  }
}

// Найти проект, которому принадлежит папка (точное совпадение или вложенность)
function findProjectSync(directory) {
  if (!directory) return null
  const idx = readIndexSync()
  const d = norm(directory)
  let best = null
  let bestLen = 0
  for (const [name, info] of Object.entries(idx)) {
    if (!info?.path) continue
    const p = norm(info.path)
    if (d === p || d.startsWith(p + "/")) {
      if (p.length > bestLen) {
        best = name
        bestLen = p.length
      }
    }
  }
  return best
}

// Синхронизация скиллов: OpenCode_Base/skills/<имя>/SKILL.md → ~/.config/opencode/skills/
// Мастер-копии живут в базе; в opencode копируются недостающие и обновлённые.
// Скиллы, удалённые из базы, из opencode тоже удаляются.
const SKILLS_SRC = path.join(BASE, "skills")

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

function safeSlug(value, fallback = "запись") {
  const s = String(value || "")
    .toLowerCase()
    .replace(/[\\/:*?"<>|]/g, "-")
    .replace(/[^a-zа-яё0-9_-]+/gi, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
  return s || fallback
}

function libraryRelative(file) {
  return path.relative(LIBRARY, file).replace(/\\/g, "/")
}

function insideLibrary(file) {
  const rel = path.relative(LIBRARY, path.resolve(file))
  return rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel))
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

function cleanMeta(value) {
  return String(value ?? "").replace(/[\r\n]+/g, " ").trim()
}

function renderRecord(meta, content, links, history) {
  const keys = [
    "id",
    "title",
    "type",
    "topic",
    "status",
    "created",
    "updated",
    "tags",
    "source",
    "confidence",
    "supersedes",
  ]
  const header = keys.map((k) => `${k}: ${cleanMeta(meta[k])}`).join("\n")
  return (
    `---\n${header}\n---\n\n# ${meta.title}\n\n` +
    `## Содержание\n\n${String(content || "").trim()}\n\n` +
    `## Связи\n\n${String(links || "- Пока нет.").trim()}\n\n` +
    `## История\n\n${String(history || `- [${meta.created}] Создано.`).trim()}\n`
  )
}

function readLibraryIndexSync() {
  try {
    const data = JSON.parse(readFileSync(LIB_INDEX, "utf8"))
    return Array.isArray(data.entries) ? data : { entries: [], topics: {}, count: 0 }
  } catch {
    return { entries: [], topics: {}, count: 0 }
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

function tokenize(value) {
  return [...new Set(String(value || "").toLowerCase().match(/[a-zа-яё0-9]{3,}/gi) || [])]
}

function findDuplicates(title, content, index) {
  const needle = new Set(tokenize(`${title} ${content}`))
  if (!needle.size) return []
  return index.entries
    .map((e) => {
      const hay = new Set(tokenize(`${e.title} ${e.tags} ${e.preview}`))
      let common = 0
      for (const t of needle) if (hay.has(t)) common++
      return { ...e, score: common / Math.max(needle.size, 1) }
    })
    .filter((e) => e.score >= 0.45)
    .sort((a, b) => b.score - a.score)
    .slice(0, 5)
}

function locateEntry(idOrPath) {
  const value = String(idOrPath || "").trim()
  if (!value) return null
  const index = readLibraryIndexSync()
  const item = index.entries.find((e) => e.id === value || e.path === value)
  if (item) {
    const file = path.resolve(LIBRARY, item.path)
    if (insideLibrary(file) && existsSync(file)) return file
  }
  const direct = path.resolve(LIBRARY, value)
  if (insideLibrary(direct) && existsSync(direct)) return direct
  for (const file of [...walkLibraryFiles(LIB_ENTRIES), ...walkLibraryFiles(LIB_ARCHIVE)]) {
    const parsed = parseRecord(readFileSync(file, "utf8"))
    if (parsed.meta.id === value) return file
  }
  return null
}

async function librarySearch(query, topic, status, limit = 10) {
  let index = readLibraryIndexSync()
  if (!index.updated) index = await rebuildLibraryIndex(false)
  const terms = tokenize(query)
  const max = Math.max(1, Math.min(Number(limit) || 10, 50))
  const results = []
  for (const e of index.entries) {
    if (topic && e.topic.toLowerCase() !== String(topic).toLowerCase()) continue
    if (status && e.status !== status) continue
    const file = path.resolve(LIBRARY, e.path)
    const content = existsSync(file) ? readFileSync(file, "utf8") : ""
    const title = e.title.toLowerCase()
    const tags = e.tags.toLowerCase()
    const body = content.toLowerCase()
    let score = terms.length ? 0 : 1
    for (const t of terms) {
      if (title.includes(t)) score += 8
      if (tags.includes(t)) score += 5
      if (e.topic.toLowerCase().includes(t)) score += 3
      if (body.includes(t)) score += 1
    }
    if (score > 0) results.push({ ...e, score })
  }
  results.sort((a, b) => b.score - a.score || String(b.updated).localeCompare(String(a.updated)))
  return results.slice(0, max)
}

export const MemoryBasePlugin = async (ctx) => {
  await fs.mkdir(SESSIONS, { recursive: true })
  await fs.mkdir(PROJECTS, { recursive: true })
  ensureLibrarySync()
  if (!existsSync(LIB_INDEX)) await rebuildLibraryIndex(false)
  syncSkills()

  // какая модель работала в каждой сессии (обновляется при каждом сообщении)
  const sessionModel = new Map()

  return {
    tool: {
      memory_save: tool({
        description:
          "Сохранить стойкий факт о пользователе в базу памяти OpenCode_Base. Используй для долговременных фактов: проекты, предпочтения, правила, решения, статус работ. НЕ используй для временных деталей текущей задачи.",
        args: {
          file: tool.schema
            .enum(["profile", "projects", "facts"])
            .describe("Куда сохранить: profile — о пользователе, projects — про проекты, facts — правила и решения"),
          text: tool.schema.string().describe("Факт одной фразой на русском"),
        },
        async execute(args) {
          const file = path.join(BASE, `${args.file}.md`)
          const old = await readFileSafe(file)
          if (old.includes(args.text)) return "Такой факт уже есть в базе — пропущен."
          await fs.appendFile(file, `- [${today()}] ${args.text}\n`, "utf8")
          return `Сохранено в ${args.file}.md: ${args.text}`
        },
      }),

      memory_read: tool({
        description: "Прочитать файлы базы памяти OpenCode_Base. Без аргументов читает все три основных файла.",
        args: {
          file: tool.schema
            .enum(["profile", "projects", "facts"])
            .optional()
            .describe("Какой файл прочитать; если не указан — все"),
        },
        async execute(args) {
          const names = args.file ? [args.file] : ["profile", "projects", "facts"]
          const out = []
          for (const n of names) {
            const text = await readFileSafe(path.join(BASE, `${n}.md`))
            out.push(`===== ${n}.md =====\n${text || "(файл пуст или отсутствует)"}`)
          }
          return out.join("\n\n")
        },
      }),

      memory_search: tool({
        description: "Поиск по всей базе памяти OpenCode_Base (профиль, проекты, факты, папки проектов и журналы нейросетей).",
        args: {
          query: tool.schema.string().describe("Что искать (без учёта регистра)"),
        },
        async execute(args) {
          const hits = []
          async function walk(dir) {
            let entries = []
            try {
              entries = await fs.readdir(dir, { withFileTypes: true })
            } catch {
              return
            }
            for (const e of entries) {
              const p = path.join(dir, e.name)
              if (e.isDirectory()) await walk(p)
              else if (e.name.endsWith(".md")) {
                const text = await fs.readFile(p, "utf8")
                const q = args.query.toLowerCase()
                text.split("\n").forEach((line, i) => {
                  if (line.toLowerCase().includes(q))
                    hits.push(`${path.relative(BASE, p)}:${i + 1}: ${line.trim()}`)
                })
              }
            }
          }
          await walk(BASE)
          return hits.length ? hits.slice(0, 50).join("\n") : "По запросу ничего не найдено."
        },
      }),

      memory_log_work: tool({
        description:
          "Зафиксировать выполненную работу по текущему проекту в базу: что сделано, какие файлы изменены, итог. Вызывай после каждого завершённого заметного этапа работы. Проект и папка твоей нейросети определятся автоматически.",
        args: {
          "описание": tool.schema.string().describe("Что сделано: задачи, изменения, результаты — 1–3 предложения на русском"),
          ai: tool.schema
            .string()
            .optional()
            .describe("Имя твоей нейросети (DeepSeek, GLM, Kimi, Qwen, Claude, Gemini, GPT...), если знаешь. Если не указано — определится автоматически."),
        },
        async execute(args, context) {
          const project = findProjectSync(context.directory)
          if (!project)
            return (
              `Папка "${context.directory}" не зарегистрирована как проект в базе. ` +
              `Новый проект создаётся командой /проект. Факт можно сохранить и в общий файл через memory_save.`
            )
          let ai = args.ai ? sanitize(args.ai) : ""
          if (!ai) {
            const m = sessionModel.get(context.sessionID)
            ai = m ? aiName(m.providerID, m.modelID) : "Нейросеть"
          }
          const dir = path.join(PROJECTS, project, ai)
          await fs.mkdir(dir, { recursive: true })
          const file = path.join(dir, "work.md")
          if (!(await readFileSafe(file))) {
            await fs.writeFile(file, `# Работа: ${ai} — проект «${project}»\n`, "utf8")
          }
          await fs.appendFile(file, `- [${today()}] ${args["описание"]}\n`, "utf8")
          return `Записано в projects/${project}/${ai}/work.md`
        },
      }),

      library_status: tool({
        description:
          "Показать состояние библиотеки NCP: количество записей и тем, последние изменения и активную память. Используй в начале работы с библиотекой или после потери контекста.",
        args: {},
        async execute() {
          const index = await rebuildLibraryIndex(false)
          const active = (await readFileSafe(LIB_ACTIVE)).trim()
          const latest = index.entries.slice(0, 5).map((e) => `- ${e.id}: ${e.title} [${e.status}]`).join("\n")
          return (
            `Библиотека NCP: ${index.count} записей, ${Object.keys(index.topics).length} тем.\n` +
            `Темы: ${Object.entries(index.topics).map(([k, v]) => `${k} (${v})`).join(", ") || "пока нет"}.\n\n` +
            `Последние записи:\n${latest || "- Пока нет."}\n\n` +
            `===== АКТИВНАЯ ПАМЯТЬ =====\n${active || "(пусто)"}`
          )
        },
      }),

      library_search: tool({
        description:
          "Найти знания в библиотеке NCP по словам, теме и статусу. Перед созданием новой записи обязательно ищи возможные дубликаты.",
        args: {
          query: tool.schema.string().describe("Слова или фраза для поиска; пустая строка выводит последние записи"),
          topic: tool.schema.string().optional().describe("Точная тема, если нужен фильтр"),
          status: tool.schema.enum(LIB_STATUSES).optional().describe("Статус записи"),
          limit: tool.schema.number().optional().describe("Сколько результатов показать, от 1 до 50"),
        },
        async execute(args) {
          const hits = await librarySearch(args.query, args.topic, args.status, args.limit)
          if (!hits.length) return "В библиотеке ничего подходящего не найдено."
          return hits
            .map(
              (e, i) =>
                `${i + 1}. ${e.title}\n` +
                `   ID: ${e.id} | тема: ${e.topic} | тип: ${e.type} | статус: ${e.status}\n` +
                `   ${e.preview || "(без краткого содержания)"}`
            )
            .join("\n\n")
        },
      }),

      library_read: tool({
        description: "Прочитать полную запись библиотеки NCP по её ID или относительному пути из каталога.",
        args: {
          id: tool.schema.string().describe("ID записи (ncp-...) или путь относительно папки библиотека"),
        },
        async execute(args) {
          const file = locateEntry(args.id)
          if (!file) return `Запись "${args.id}" не найдена. Сначала используй library_search.`
          return `===== ${libraryRelative(file)} =====\n${await fs.readFile(file, "utf8")}`
        },
      }),

      library_save: tool({
        description:
          "Создать новое долговременное знание в библиотеке NCP. Инструмент проверяет возможные дубликаты; если они найдены, сначала обнови существующую запись либо явно разреши отдельную запись.",
        args: {
          title: tool.schema.string().describe("Короткое уникальное название"),
          content: tool.schema.string().describe("Полное содержание знания"),
          type: tool.schema.enum(LIB_TYPES).describe("Тип записи"),
          topic: tool.schema.string().describe("Тема: имя папки, например opencode, ремонт, работа"),
          tags: tool.schema.string().optional().describe("Ключевые слова через запятую"),
          source: tool.schema.string().optional().describe("Источник: пользователь, путь к файлу, URL или вывод анализа"),
          confidence: tool.schema.enum(LIB_CONFIDENCE).optional().describe("Уверенность в достоверности"),
          links: tool.schema.string().optional().describe("Связанные ID или пояснения"),
          supersedes: tool.schema.string().optional().describe("ID старой записи, которую заменяет новая"),
          allow_duplicate: tool.schema.boolean().optional().describe("Создать отдельно, даже если найдены похожие записи"),
        },
        async execute(args) {
          const index = await rebuildLibraryIndex(false)
          const duplicates = findDuplicates(args.title, args.content, index)
          if (duplicates.length && !args.allow_duplicate) {
            return (
              "Похожая информация уже есть. Новая запись пока НЕ создана. Проверь и при необходимости используй library_update:\n" +
              duplicates.map((e) => `- ${e.id}: ${e.title} (сходство ${Math.round(e.score * 100)}%)`).join("\n") +
              "\nЕсли это действительно отдельное знание, повтори с allow_duplicate=true."
            )
          }
          const stamp = now()
          const id = `ncp-${stamp.replace(/[-:TZ.]/g, "").slice(0, 14)}-${randomBytes(2).toString("hex")}`
          const topic = safeSlug(args.topic, "общее")
          const title = cleanMeta(args.title) || "Без названия"
          const meta = {
            id,
            title,
            type: args.type,
            topic,
            status: "active",
            created: stamp,
            updated: stamp,
            tags: cleanMeta(args.tags || ""),
            source: cleanMeta(args.source || "пользователь"),
            confidence: args.confidence || "medium",
            supersedes: cleanMeta(args.supersedes || ""),
          }
          const links = args.links ? `- ${String(args.links).trim()}` : "- Пока нет."
          const file = path.join(LIB_ENTRIES, topic, `${id}-${safeSlug(title)}.md`)
          await atomicWrite(file, renderRecord(meta, args.content, links, `- [${stamp}] Создано.`))
          await rebuildLibraryIndex(false)
          await libraryLog("create", `${id} — ${title} (${topic})`)
          return `Создана запись ${id}: ${libraryRelative(file)}`
        },
      }),

      library_update: tool({
        description:
          "Обновить существующую запись NCP. Сохраняет ID, добавляет историю изменения, обновляет индекс. Для удаления используй статус archived — физически файл не удаляется.",
        args: {
          id: tool.schema.string().describe("ID изменяемой записи"),
          title: tool.schema.string().optional().describe("Новое название"),
          content: tool.schema.string().optional().describe("Новое полное содержание"),
          type: tool.schema.enum(LIB_TYPES).optional().describe("Новый тип"),
          topic: tool.schema.string().optional().describe("Новая тема"),
          status: tool.schema.enum(LIB_STATUSES).optional().describe("Новый статус"),
          tags: tool.schema.string().optional().describe("Новый список тегов через запятую"),
          source: tool.schema.string().optional().describe("Новый или дополненный источник"),
          confidence: tool.schema.enum(LIB_CONFIDENCE).optional().describe("Новая уверенность"),
          supersedes: tool.schema.string().optional().describe("ID заменённой записи"),
          links: tool.schema.string().optional().describe("Новый раздел связей"),
          reason: tool.schema.string().describe("Зачем внесено изменение"),
        },
        async execute(args) {
          const file = locateEntry(args.id)
          if (!file) return `Запись "${args.id}" не найдена.`
          const parsed = parseRecord(await fs.readFile(file, "utf8"))
          const old = { ...parsed.meta }
          const stamp = now()
          const meta = {
            ...old,
            title: cleanMeta(args.title ?? old.title),
            type: args.type ?? old.type,
            topic: safeSlug(args.topic ?? old.topic, "общее"),
            status: args.status ?? old.status,
            updated: stamp,
            tags: cleanMeta(args.tags ?? old.tags),
            source: cleanMeta(args.source ?? old.source),
            confidence: args.confidence ?? old.confidence,
            supersedes: cleanMeta(args.supersedes ?? old.supersedes),
          }
          const content = args.content ?? section(parsed.body, "Содержание")
          const links = args.links ?? section(parsed.body, "Связи") ?? "- Пока нет."
          const previousHistory = section(parsed.body, "История")
          const history = `${previousHistory ? previousHistory + "\n" : ""}- [${stamp}] Обновлено: ${cleanMeta(args.reason)}`
          const root = meta.status === "archived" ? LIB_ARCHIVE : LIB_ENTRIES
          const target = path.join(root, meta.topic, `${meta.id}-${safeSlug(meta.title)}.md`)
          await atomicWrite(target, renderRecord(meta, content, links, history))
          if (path.resolve(target) !== path.resolve(file) && insideLibrary(file)) await fs.unlink(file)
          await rebuildLibraryIndex(false)
          await libraryLog("update", `${meta.id} — ${meta.title}: ${cleanMeta(args.reason)}`)
          return `Обновлена запись ${meta.id}: ${libraryRelative(target)}`
        },
      }),

      library_checkpoint: tool({
        description:
          "Сохранить контрольную точку контекста в активную память NCP. Вызывай перед сжатием контекста, завершением большой задачи или передачей работы новой сессии.",
        args: {
          goal: tool.schema.string().describe("Текущая цель работы"),
          summary: tool.schema.string().describe("Что уже сделано и что важно помнить"),
          decisions: tool.schema.string().optional().describe("Подтверждённые решения, по одному на строку"),
          next_steps: tool.schema.string().optional().describe("Следующие действия, по одному на строку"),
          related_ids: tool.schema.string().optional().describe("Связанные ID записей через запятую"),
        },
        async execute(args) {
          const stamp = now()
          const bullets = (value, empty) => {
            const rows = String(value || "").split(/\r?\n/).map((s) => s.trim()).filter(Boolean)
            return rows.length ? rows.map((s) => `- ${s.replace(/^[-*]\s*/, "")}`).join("\n") : `- ${empty}`
          }
          const text =
            `# Активная память NCP\n\n` +
            `- **Последняя контрольная точка:** ${stamp}\n` +
            `- **Текущая цель:** ${cleanMeta(args.goal)}\n\n` +
            `## Краткое состояние\n\n${String(args.summary).trim()}\n\n` +
            `## Важные решения\n\n${bullets(args.decisions, "Пока нет.")}\n\n` +
            `## Незавершённое\n\n${bullets(args.next_steps, "Пока нет.")}\n\n` +
            `## Связанные записи\n\n${bullets(args.related_ids, "Пока нет.")}\n`
          await atomicWrite(LIB_ACTIVE, text)
          await libraryLog("checkpoint", cleanMeta(args.goal))
          return `Контрольная точка сохранена в ${libraryRelative(LIB_ACTIVE)}.`
        },
      }),

      library_reindex: tool({
        description: "Полностью пересобрать машинный индекс и человекочитаемый каталог библиотеки NCP.",
        args: {},
        async execute() {
          const data = await rebuildLibraryIndex(true)
          return `Индекс перестроен: ${data.count} записей, ${Object.keys(data.topics).length} тем.`
        },
      }),
    },

    "chat.message": async (input) => {
      if (input?.sessionID && input?.model)
        sessionModel.set(input.sessionID, {
          providerID: input.model.providerID,
          modelID: input.model.modelID,
        })
    },

    event: async ({ event }) => {
      if (event.type === "session.idle") {
        try {
          const sid = event.properties?.sessionID
          if (!sid) return
          let title = ""
          let dir = ctx.directory
          try {
            const res = await ctx.client.session.get({ sessionID: sid })
            const info = res?.data ?? res
            title = info?.title || ""
            if (info?.directory) dir = info.directory
            else if (info?.worktree) dir = info.worktree
          } catch {}

          const proj = findProjectSync(dir)
          debug(`session.idle sid=${sid} dir=${dir} proj=${proj}`)

          // общий журнал сессий
          const month = new Date().toISOString().slice(0, 7)
          mkdirSync(SESSIONS, { recursive: true })
          appendFileSync(
            path.join(SESSIONS, `${month}.md`),
            `- [${now()}] сессия \`${sid}\`${title ? ` — ${title}` : ""}${dir ? ` — ${dir}` : ""}\n`,
            "utf8"
          )

          // журнал проекта + папка нейросети
          if (proj) {
            const m = sessionModel.get(sid)
            const ai = m ? aiName(m.providerID, m.modelID) : "Нейросеть"
            const aiDir = path.join(PROJECTS, proj, ai)
            mkdirSync(aiDir, { recursive: true })
            appendFileSync(
              path.join(aiDir, "sessions.md"),
              `- [${now()}] ${title || "сессия"} (\`${sid}\`)\n`,
              "utf8"
            )
            debug(`project log written: ${proj}/${ai}/sessions.md`)
          }
        } catch (e) {
          debug(`session.idle ERROR: ${e && e.stack ? e.stack : String(e)}`)
        }
      }
    },

    "experimental.session.compacting": async (input, output) => {
      const active = readFileSync(LIB_ACTIVE, "utf8")
      output.context.push(
        `ВАЖНО: контекст сейчас будет сжат. До продолжения обязательно: ` +
          `1) вызови library_checkpoint и сохрани текущую цель, сделанное, решения и следующий шаг; ` +
          `2) стойкие знания сохрани через library_save или library_update; ` +
          `3) работу по проекту зафиксируй через memory_log_work. ` +
          `После сжатия восстанови ход работы из активной памяти ниже.\n\n` +
          `===== АКТИВНАЯ ПАМЯТЬ NCP =====\n${active}`
      )
    },
  }
}

export default MemoryBasePlugin
