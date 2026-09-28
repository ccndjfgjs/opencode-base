#!/usr/bin/env node
// Сканер сессий opencode для базы OpenCode_Base.
// list                — все сессии: создана, использована, название, папка
// list --dir <путь>   — только сессии из указанной папки
// delete <id> [id...] — удалить сессии через официальный CLI opencode

const { DatabaseSync } = require("node:sqlite")
const { execFileSync } = require("node:child_process")
const path = require("node:path")

const DB = path.join(
  process.env.USERPROFILE || process.env.HOME,
  ".local/share/opencode/opencode.db"
)

const fmt = (ms) => {
  if (!ms) return "—"
  const d = new Date(ms)
  const pad = (n) => String(n).padStart(2, "0")
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function list(dirFilter) {
  const db = new DatabaseSync(DB, { readOnly: true })
  let rows = db
    .prepare(
      `SELECT id, title, directory, time_created, time_updated, time_archived
       FROM session ORDER BY time_updated DESC`
    )
    .all()
  db.close()
  if (dirFilter) {
    const want = dirFilter.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase()
    rows = rows.filter((r) => (r.directory || "").replace(/\\/g, "/").toLowerCase() === want)
  }
  for (const r of rows) {
    const arch = r.time_archived ? " [архив]" : ""
    console.log(
      `${r.id}  создана ${fmt(r.time_created)}  использована ${fmt(r.time_updated)}${arch}\n    ${r.title || "(без названия)"}  |  ${r.directory || "—"}`
    )
  }
  console.log(`\nИтого сессий: ${rows.length}`)
}

function remove(ids) {
  if (!ids.length) {
    console.error("Укажите хотя бы один sessionID: node sessions.js delete ses_...")
    process.exit(1)
  }
  for (const id of ids) {
    if (!/^ses_[A-Za-z0-9]+$/.test(id)) {
      console.error(`Подозрительный sessionID, пропущен: ${id}`)
      process.exitCode = 1
      continue
    }
    try {
      execFileSync(`opencode session delete ${id}`, { stdio: "pipe", shell: true })
      console.log(`Удалена: ${id}`)
    } catch (e) {
      console.error(`Не удалось удалить ${id}: ${e.message}`)
      process.exitCode = 1
    }
  }
}

const [cmd, ...rest] = process.argv.slice(2)
if (cmd === "list") {
  const i = rest.indexOf("--dir")
  list(i >= 0 ? rest[i + 1] : null)
} else if (cmd === "delete") {
  remove(rest)
} else {
  console.log(
    "Использование:\n" +
      "  node sessions.js list                 — показать все сессии\n" +
      "  node sessions.js list --dir <путь>    — сессии конкретной папки\n" +
      "  node sessions.js delete <id> [id...]  — удалить сессии (через opencode session delete)"
  )
}
