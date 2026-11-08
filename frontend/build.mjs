import { build } from "esbuild";
import { execFileSync } from "node:child_process";
import { cp, mkdir, readFile, readdir, rename, rm, writeFile } from "node:fs/promises";
import { gzipSync } from "node:zlib";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

process.chdir(fileURLToPath(new URL(".", import.meta.url)));
await rm("dist", { recursive: true, force: true });
await mkdir("dist/assets", { recursive: true });
await cp("public", "dist", { recursive: true });
const result = await build({
  entryPoints: ["src/main.tsx"],
  bundle: true,
  minify: true,
  format: "esm",
  target: ["es2022"],
  outdir: "dist/assets",
  entryNames: "[name]-[hash]",
  metafile: true,
  jsx: "automatic",
  define: { "process.env.NODE_ENV": '"production"' },
});
execFileSync(
  process.execPath,
  [
    "node_modules/@tailwindcss/cli/dist/index.mjs",
    "-i",
    "src/index.css",
    "-o",
    "dist/assets/app.css",
    "--minify",
  ],
  { stdio: "inherit" },
);
const css = await readFile("dist/assets/app.css");
const cssName = `app-${createHash("sha256").update(css).digest("hex").slice(0, 12)}.css`;
await rename("dist/assets/app.css", `dist/assets/${cssName}`);
const entry = Object.entries(result.metafile.outputs)
  .find(([, value]) => value.entryPoint === "src/main.tsx")[0]
  .replace(/^dist\//, "/");
const html = (await readFile("index.html", "utf8"))
  .replace(
    '<script type="module" src="/src/main.tsx"></script>',
    `<script type="module" src="${entry}"></script>`,
  )
  .replace("</head>", `<link rel="stylesheet" href="/assets/${cssName}" /></head>`);
await writeFile("dist/index.html", html);
for (const name of await readdir("dist/assets")) {
  if (/\.(js|css)$/.test(name)) {
    await writeFile(
      `dist/assets/${name}.gz`,
      gzipSync(await readFile(`dist/assets/${name}`), { level: 9 }),
    );
  }
}
console.log("Built frontend/dist with esbuild and Tailwind CSS.");
