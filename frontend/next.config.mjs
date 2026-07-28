/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export — генерит папку out/ с чистой статикой,
  // которую Electron грузит через loadFile().
  output: "export",
  // Относительные пути к ассетам — обязательно для file:// загрузки в Electron.
  // Иначе index.html ссылается на /_next/... (абсолютный путь) и не находится.
  assetPrefix: "./",
  // images.unoptimized — иначе Next требует Image Optimization API,
  // которого нет в static export.
  images: { unoptimized: true },
  // trailingSlash — чтобы file:// ссылки на подпапки работали корректно
  trailingSlash: true,
  // Отключаем eslint во время build (не блокирует сборку)
  eslint: { ignoreDuringBuilds: true },
  reactStrictMode: true,
};

export default nextConfig;
