import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const virtualEnvPython = process.platform === "win32"
  ? join(projectRoot, ".venv", "Scripts", "python.exe")
  : join(projectRoot, ".venv", "bin", "python");
const python = process.env.FOCUSFORGE_PYTHON || virtualEnvPython;

if (!process.env.FOCUSFORGE_PYTHON && !existsSync(virtualEnvPython)) {
  console.error("FocusForge AI's Python virtual environment was not found.");
  console.error("Create it with: python -m venv .venv");
  console.error("Install dependencies with: .venv\\Scripts\\python.exe -m pip install -r backend\\requirements.txt");
  process.exit(1);
}

const port = process.env.PORT?.trim() || "8000";
const server = spawn(
  python,
  [
    "-m", "uvicorn", "backend.app.main:app",
    "--host", "127.0.0.1", "--port", port,
  ],
  { cwd: projectRoot, stdio: "inherit", env: process.env },
);

server.on("error", (error) => {
  console.error(`Could not start the FocusForge AI server: ${error.message}`);
  process.exitCode = 1;
});

server.on("exit", (code, signal) => {
  process.exitCode = signal ? 1 : (code ?? 1);
});
