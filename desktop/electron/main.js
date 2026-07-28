/**
 * Electron main process.
 * Запускает Python backend, ждёт health-check, открывает окно с UI.
 * При выходе — аккуратно убивает backend.
 */
const { app, BrowserWindow, dialog, shell, Menu } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const http = require("http");

// Убираем дефолтное меню Electron (File/Edit/View/Window/Help)
Menu.setApplicationMenu(null);

const BACKEND_PORT = 8000;
const BACKEND_HOST = "127.0.0.1";

let mainWindow = null;
let backendProcess = null;
let splashWindow = null;

// ---------------------------------------------------------------- paths

function getBackendCommand() {
  if (app.isPackaged) {
    // Собранный PyInstaller exe рядом с приложением
    return {
      cmd: path.join(process.resourcesPath, "backend", "yascraper-backend.exe"),
      args: [],
      cwd: path.join(process.resourcesPath, "backend"),
    };
  }
  // Dev режим: запускаем из venv backend
  return {
    cmd: "C:\\ggf\\backend\\.venv\\Scripts\\python.exe",
    args: ["-m", "uvicorn", "app.main:app",
           "--host", BACKEND_HOST, "--port", String(BACKEND_PORT)],
    cwd: "C:\\ggf\\backend",
  };
}

function getFrontendPath() {
  if (app.isPackaged) {
    // Статика в extraResources (рядом с backend), НЕ в asar
    return path.join(process.resourcesPath, "frontend", "index.html");
  }
  // Dev: собранная статика Next.js (после `npm run build` во frontend)
  return path.join(__dirname, "..", "..", "frontend", "out", "index.html");
}

function getBackendUrl() {
  return `http://${BACKEND_HOST}:${BACKEND_PORT}`;
}

// ---------------------------------------------------------------- backend

function startBackend() {
  const { cmd, args, cwd } = getBackendCommand();
  console.log(`[backend] spawn: ${cmd} ${args.join(" ")} (cwd: ${cwd})`);

  backendProcess = spawn(cmd, args, {
    cwd,
    windowsHide: true,
    env: {
      ...process.env,
      // Подавляем лишний вывод uvicorn в консоль Electron
      UVICORN_LOG_LEVEL: "warning",
      PYTHONUNBUFFERED: "1",
    },
  });

  backendProcess.stdout.on("data", (data) => {
    const msg = data.toString().trim();
    if (msg) console.log(`[backend:out] ${msg}`);
  });

  backendProcess.stderr.on("data", (data) => {
    const msg = data.toString().trim();
    if (msg) console.error(`[backend:err] ${msg}`);
  });

  backendProcess.on("exit", (code, signal) => {
    console.log(`[backend] exited code=${code} signal=${signal}`);
    backendProcess = null;
  });

  backendProcess.on("error", (err) => {
    console.error(`[backend] spawn error:`, err);
    dialog.showErrorBox(
      "Ошибка запуска backend",
      `Не удалось запустить backend-процесс:\n${err.message}\n\n` +
      `Проверьте, что файл существует и доступен.`,
    );
  });
}

function stopBackend() {
  if (!backendProcess) return;
  console.log("[backend] stopping…");
  try {
    // На Windows корректно завершаем через taskkill /T (дерево процессов)
    if (process.platform === "win32") {
      spawn("taskkill", ["/pid", String(backendProcess.pid), "/f", "/t"],
            { windowsHide: true });
    } else {
      backendProcess.kill("SIGTERM");
    }
  } catch (e) {
    console.error("[backend] stop error:", e);
  }
  backendProcess = null;
}

function waitForBackend(maxAttempts = 60, intervalMs = 1000) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const check = () => {
      attempts++;
      const req = http.get(
        `http://${BACKEND_HOST}:${BACKEND_PORT}/health`,
        (res) => {
          if (res.statusCode === 200) {
            resolve();
          } else if (attempts >= maxAttempts) {
            reject(new Error(`health check failed after ${attempts} attempts`));
          } else {
            setTimeout(check, intervalMs);
          }
          res.resume();
        },
      );
      req.on("error", () => {
        if (attempts >= maxAttempts) {
          reject(new Error("backend not reachable"));
        } else {
          setTimeout(check, intervalMs);
        }
      });
      req.setTimeout(2000, () => {
        req.destroy();
        if (attempts >= maxAttempts) {
          reject(new Error("health check timeout"));
        } else {
          setTimeout(check, intervalMs);
        }
      });
    };
    check();
  });
}

// ---------------------------------------------------------------- windows

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 420,
    height: 280,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    movable: false,
    center: true,
    show: true,
  });
  splashWindow.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(`
    <html><body style="margin:0;padding:0;height:100vh;display:flex;
      flex-direction:column;align-items:center;justify-content:center;
      background:rgba(20,20,24,0.96);color:#f5f5f5;font-family:'Segoe UI',system-ui,sans-serif;
      border-radius:14px;-webkit-app-region:drag;">
      <div style="font-size:42px;margin-bottom:12px;">🗺️</div>
      <div style="font-size:18px;font-weight:600;margin-bottom:4px;">Yandex Maps Scraper</div>
      <div style="font-size:13px;color:#9ca3af;">Запуск backend…</div>
      <div style="margin-top:18px;width:180px;height:3px;background:#2a2a30;border-radius:2px;overflow:hidden;">
        <div style="height:100%;width:40%;background:#f59e0b;border-radius:2px;
          animation:slide 1.2s ease-in-out infinite;"></div>
      </div>
      <style>
        @keyframes slide {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(350%); }
        }
      </style>
    </body></html>
  `));
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 640,
    show: false,
    backgroundColor: "#0a0a0c",
    titleBarStyle: process.platform === "win32" ? "default" : "hiddenInset",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  // Внешние ссылки открываем в браузере, не в приложении
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("http")) {
      shell.openExternal(url);
      return { action: "deny" };
    }
    return { action: "allow" };
  });

  const frontendPath = getFrontendPath();
  mainWindow.loadFile(frontendPath);

  mainWindow.once("ready-to-show", () => {
    if (splashWindow) {
      splashWindow.close();
      splashWindow = null;
    }
    mainWindow.show();
    // В dev можно раскомментировать для DevTools
    // mainWindow.webContents.openDevTools();
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

// ---------------------------------------------------------------- lifecycle

app.whenReady().then(async () => {
  createSplash();
  startBackend();

  try {
    await waitForBackend();
    console.log("[main] backend ready");
    createMainWindow();
  } catch (err) {
    console.error("[main] backend failed:", err);
    if (splashWindow) {
      splashWindow.close();
      splashWindow = null;
    }
    dialog.showErrorBox(
      "Backend не запустился",
      `Backend не ответил на health-check за 60 секунд.\n\n` +
      `Возможные причины:\n` +
      `• Порт ${BACKEND_PORT} занят другим процессом\n` +
      `• Ошибка в Python-бэкенде\n\n` +
      `Запустите приложение ещё раз. Если проблема повторяется — ` +
      `освободите порт ${BACKEND_PORT} или проверьте логи.`,
    );
    app.quit();
  }
});

app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  stopBackend();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0 && mainWindow === null) {
    createMainWindow();
  }
});

// Корректное завершение дочерних процессов при падении главного
process.on("exit", () => stopBackend());
process.on("SIGINT", () => { stopBackend(); process.exit(0); });
process.on("SIGTERM", () => { stopBackend(); process.exit(0); });
