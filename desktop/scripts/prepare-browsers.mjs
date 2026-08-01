/**
 * Кладёт браузер Playwright в сборку бэкенда перед упаковкой.
 *
 * Ни PyInstaller, ни electron-builder браузеры не тащат: они лежат отдельно
 * в %LOCALAPPDATA%\ms-playwright и в spec не попадают. Раньше это был ручной
 * шаг, о котором знал только тот, кто собирал, — и установщик уезжал рабочим
 * на вид, но падал на первом же поиске с «Please run playwright install».
 *
 * Скрипт цепляется к `npm run dist`, поэтому забыть про него больше нельзя.
 *
 * По умолчанию кладётся только headless-версия: приложение работает в headless
 * (HEADLESS=true), а полный Chromium весит ещё 416 МБ. Нужен и он — соберите
 * с INCLUDE_FULL_CHROMIUM=1.
 */
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const BACKEND_DIST = join(process.cwd(), "..", "backend", "dist", "yascraper-backend");
// run.py ищет браузеры именно здесь: <папка exe>/browsers/ms-playwright/
const DEST = join(BACKEND_DIST, "browsers", "ms-playwright");

const SOURCE = join(
  process.env.LOCALAPPDATA ?? join(homedir(), "AppData", "Local"),
  "ms-playwright",
);

const wanted = ["chromium_headless_shell"];
if (process.env.INCLUDE_FULL_CHROMIUM === "1") {
  wanted.push("chromium");
}

function fail(message, hint) {
  console.error(`\n[browsers] ${message}`);
  if (hint) console.error(`[browsers] ${hint}`);
  process.exit(1);
}

/** Самая свежая сборка браузера: имена вида chromium_headless_shell-1228. */
function latestBuild(prefix) {
  const rx = new RegExp(`^${prefix}-(\\d+)$`);
  const builds = readdirSync(SOURCE, { withFileTypes: true })
    .filter((e) => e.isDirectory() && rx.test(e.name))
    .map((e) => ({ name: e.name, build: Number(e.name.match(rx)[1]) }))
    .sort((a, b) => b.build - a.build);
  return builds[0] ?? null;
}

if (!existsSync(BACKEND_DIST)) {
  fail(
    `нет сборки бэкенда: ${BACKEND_DIST}`,
    "сначала соберите её: cd ../backend && .venv\\Scripts\\pyinstaller yascraper.spec",
  );
}

if (!existsSync(SOURCE)) {
  fail(
    `не нашёл браузеры Playwright в ${SOURCE}`,
    "установите их: cd ../backend && .venv\\Scripts\\playwright install chromium",
  );
}

mkdirSync(DEST, { recursive: true });

for (const prefix of wanted) {
  const found = latestBuild(prefix);
  if (!found) {
    fail(
      `в ${SOURCE} нет ни одной сборки ${prefix}`,
      "установите: cd ../backend && .venv\\Scripts\\playwright install chromium",
    );
  }

  const target = join(DEST, found.name);
  // Старые версии убираем: иначе установщик пухнет от каждой прошлой сборки.
  for (const entry of readdirSync(DEST, { withFileTypes: true })) {
    if (entry.isDirectory() && entry.name.startsWith(`${prefix}-`) && entry.name !== found.name) {
      rmSync(join(DEST, entry.name), { recursive: true, force: true });
      console.log(`[browsers] убрал устаревшую ${entry.name}`);
    }
  }

  if (existsSync(target)) {
    console.log(`[browsers] ${found.name} уже на месте`);
  } else {
    console.log(`[browsers] копирую ${found.name}…`);
    cpSync(join(SOURCE, found.name), target, { recursive: true });
  }
}

// Проверяем не наличие папки, а именно исполняемый файл: пустая или
// оборванная копия выглядит как успех, а падает уже у пользователя.
const shell = latestBuild("chromium_headless_shell");
const exe = join(
  DEST,
  shell.name,
  "chrome-headless-shell-win64",
  "chrome-headless-shell.exe",
);
if (!existsSync(exe)) {
  fail(`браузер скопировался, но ${exe} не найден — копия неполная`);
}

console.log("[browsers] готово");
