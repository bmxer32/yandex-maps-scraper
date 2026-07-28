/**
 * Preload script — мост между main и renderer.
 * Сейчас фронт ходит к backend по http напрямую (CORS открыт),
 * preload оставлен для будущих нативных фич (диалоги, FS).
 */
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("electron", {
  /** URL backend-сервера (для подсказки фронту, если env недоступен). */
  backendUrl: "http://127.0.0.1:8000",
  /** Версия приложения из package.json. */
  appVersion: process.env.npm_package_version || "0.0.0",
  /** Признак packaged-режима (vs dev). */
  isPackaged: process.versions.electron !== undefined,
});
