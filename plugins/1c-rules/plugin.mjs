import { spawn } from "node:child_process"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const pluginRoot = dirname(fileURLToPath(import.meta.url))
const script = join(pluginRoot, "scripts", "invoke-install.ps1")

function hostTool() {
  if (process.env.KILO_CLI || process.env.KILOCODE) return "kilocode"
  return "opencode"
}

function runEnsure(projectRoot, tool) {
  return new Promise((resolve) => {
    const win = process.platform === "win32"
    const cmd = win ? "powershell.exe" : "pwsh"
    const args = ["-NoProfile"]
    if (win) args.push("-ExecutionPolicy", "Bypass")
    args.push("-File", script, "-Action", "ensure", "-Tool", tool, "-ProjectRoot", projectRoot)
    const child = spawn(cmd, args, { stdio: "ignore", windowsHide: true })
    child.on("error", () => resolve())
    child.on("exit", () => resolve())
  })
}

export const OneCRulesPlugin = async ({ directory }) => {
  return {
    event: async ({ event }) => {
      if (!event || event.type !== "session.created") return
      const root = directory || process.cwd()
      await runEnsure(root, hostTool())
    },
  }
}

export default OneCRulesPlugin
