/**
 * Запуск Docker-стека kb_assistant (ИИ-ассистент для персональных демо).
 *
 * Стеку нужен PostgreSQL, поэтому нативно, как backend парсера, он не
 * поднимается — только через docker compose. Запуск идёт фоном и НЕ блокирует
 * окно: парсер полностью работоспособен без ассистента, просто колонка «Демо»
 * будет ждать готовности.
 *
 * Стек намеренно НЕ гасится при выходе из программы: этот же контейнер держит
 * Telegram-бота, который отвечает клиентам по разосланным ссылкам. Погасить
 * его при закрытии парсера — значит оборвать демо у всех, кому уже написали.
 */
const { app } = require("electron");
const path = require("path");
const fs = require("fs");
const http = require("http");
const { spawn } = require("child_process");

// Порт на хосте: 8000 занят бэкендом самого парсера.
const KB_HOST_PORT = 8001;
const KB_URL = `http://127.0.0.1:${KB_HOST_PORT}`;

// Поднять Postgres, Qdrant и приложение — небыстро, особенно на холодную.
const READY_ATTEMPTS = 90;
const READY_INTERVAL_MS = 2000;

let starting = false;

/**
 * Где лежит kb_assistant. По порядку:
 *   1. переменная окружения KB_PROJECT_DIR
 *   2. kb-config.json в userData: { "projectDir": "...", "autoStart": true }
 *   3. дефолт для этой машины
 * Возвращает null, если проект не найден — тогда стек просто не трогаем.
 */
function resolveConfig() {
  const fromEnv = process.env.KB_PROJECT_DIR;
  if (fromEnv) return { projectDir: fromEnv, autoStart: true };

  try {
    const cfgPath = path.join(app.getPath("userData"), "kb-config.json");
    if (fs.existsSync(cfgPath)) {
      const cfg = JSON.parse(fs.readFileSync(cfgPath, "utf-8"));
      if (cfg.projectDir) {
        return { projectDir: cfg.projectDir, autoStart: cfg.autoStart !== false };
      }
    }
  } catch (e) {
    console.error("[kb] не смог прочитать kb-config.json:", e.message);
  }

  return { projectDir: "C:\\Projects\\kb_assistant", autoStart: true };
}

function composeFile(projectDir) {
  return path.join(projectDir, "docker-compose.dev.yml");
}

/** Запустить команду, вернуть { code, stdout, stderr }. Никогда не бросает. */
function run(cmd, args, opts = {}) {
  return new Promise((resolve) => {
    let stdout = "";
    let stderr = "";
    const child = spawn(cmd, args, { windowsHide: true, ...opts });

    child.stdout?.on("data", (d) => (stdout += d.toString()));
    child.stderr?.on("data", (d) => (stderr += d.toString()));
    child.on("error", (err) => resolve({ code: -1, stdout, stderr: err.message }));
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

/**
 * Проверяем именно демон, а не CLI: `docker --version` отвечает и при
 * выключенном Docker Desktop, так что по нему нельзя понять, взлетит ли
 * compose. `docker info` обращается к демону и падает, если его нет.
 */
async function dockerAvailable() {
  const cli = await run("docker", ["--version"]);
  if (cli.code !== 0) return { ok: false, reason: "Docker не установлен" };

  const daemon = await run("docker", ["info", "--format", "{{.ServerVersion}}"]);
  if (daemon.code !== 0) return { ok: false, reason: "Docker Desktop не запущен" };

  return { ok: true };
}

/** Отвечает ли kb_assistant на health-check. */
function isReady() {
  return new Promise((resolve) => {
    const req = http.get(`${KB_URL}/api/v1/health/ready`, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(2500, () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitUntilReady(onStatus) {
  for (let i = 1; i <= READY_ATTEMPTS; i++) {
    if (await isReady()) return true;
    if (i % 5 === 0) {
      onStatus?.(`ИИ-ассистент запускается… (${i * READY_INTERVAL_MS / 1000}с)`);
    }
    await new Promise((r) => setTimeout(r, READY_INTERVAL_MS));
  }
  return false;
}

/**
 * Поднять стек kb_assistant, если он ещё не поднят.
 * @param {(msg: string) => void} [onStatus] — куда сообщать о прогрессе.
 * @returns {Promise<{ok: boolean, reason?: string}>}
 */
async function startKbStack(onStatus) {
  if (starting) return { ok: false, reason: "уже запускается" };
  starting = true;

  try {
    const cfg = resolveConfig();
    if (!cfg.autoStart) {
      return { ok: false, reason: "автозапуск отключён в kb-config.json" };
    }

    // Уже поднят (например, остался с прошлого запуска) — ничего не делаем.
    if (await isReady()) {
      console.log("[kb] стек уже отвечает");
      return { ok: true };
    }

    const file = composeFile(cfg.projectDir);
    if (!fs.existsSync(file)) {
      const reason = `не найден ${file}`;
      console.warn(`[kb] ${reason}`);
      return { ok: false, reason };
    }

    const docker = await dockerAvailable();
    if (!docker.ok) {
      console.warn(`[kb] ${docker.reason}`);
      return { ok: false, reason: docker.reason };
    }

    const env = { ...process.env, KB_HOST_PORT: String(KB_HOST_PORT) };

    onStatus?.("Поднимаю ИИ-ассистент…");
    console.log(`[kb] docker compose up -d (${file})`);
    const up = await run("docker", ["compose", "-f", file, "up", "-d"], {
      cwd: cfg.projectDir,
      env,
    });
    if (up.code !== 0) {
      const reason = (up.stderr || up.stdout || "").trim().split("\n").pop() || "ошибка docker compose";
      console.error("[kb] up failed:", up.stderr || up.stdout);
      return { ok: false, reason };
    }

    if (!(await waitUntilReady(onStatus))) {
      return { ok: false, reason: "стек не ответил на health-check" };
    }

    // Миграции после готовности БД. Идемпотентны и быстры, когда накатывать
    // нечего, — зато исключают «забыл накатить» после обновления программы.
    onStatus?.("Применяю миграции ИИ-ассистента…");
    const migrate = await run(
      "docker",
      ["compose", "-f", file, "run", "--rm", "--no-deps", "app", "alembic", "upgrade", "head"],
      { cwd: cfg.projectDir, env },
    );
    if (migrate.code !== 0) {
      console.error("[kb] миграции не прошли:", migrate.stderr || migrate.stdout);
      return { ok: false, reason: "миграции не прошли" };
    }

    console.log("[kb] стек готов");
    return { ok: true };
  } finally {
    starting = false;
  }
}

module.exports = { startKbStack, isReady, KB_URL, KB_HOST_PORT };
