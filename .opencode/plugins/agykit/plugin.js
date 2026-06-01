// agykit — opencode plugin
//
// Wraps the agykit CLI as a callable tool + lifecycle hooks.
// - Tool: agykit (run, status, doctor, quota, etc.)
// - Hook: config → auto-registers agykit agents
// - Hook: tool.execute.after → quota exhaustion detection
//
// Install: add "agykit" to the plugin array in opencode.json, then:
//   cd ~/.config/opencode && bun install ./plugins/agykit

import { tool } from "@opencode-ai/plugin";
import { execSync } from "node:child_process";

function findAgykit() {
  const paths = [
    process.env.AGYKIT,
    process.env.HOME + "/.local/bin/agykit",
    process.env.HOME + "/.local/bin/agy",
    "/usr/local/bin/agykit",
  ];
  const envPath = (process.env.PATH || "").split(":");
  for (const p of [...paths, ...envPath.map((d) => d + "/agykit")]) {
    try {
      execSync(`test -x "${p}"`, { stdio: "ignore" });
      return p;
    } catch {}
  }
  return "agykit"; // fallback — rely on PATH
}

const AGYKIT_BIN = findAgykit();

function runAgykit(cmd, args = "") {
  const full = `${AGYKIT_BIN} ${cmd} ${args}`.trim();
  try {
    return execSync(full, {
      encoding: "utf-8",
      timeout: 60_000,
      maxBuffer: 1024 * 512,
    }).trim();
  } catch (e) {
    const stderr = e.stderr?.toString().trim() || "";
    const stdout = e.stdout?.toString().trim() || "";
    return stdout || stderr || `agykit error: ${e.message}`;
  }
}

function formatOutput(raw) {
  const lines = raw.split("\n").filter(Boolean);
  if (lines.length <= 20) return raw;
  return lines.slice(0, 20).join("\n") + `\n… (${lines.length - 20} more lines)`;
}

export const AgykitPlugin = async () => ({
  tools: {
    agykit: tool({
      description:
        "Run agykit commands: status, doctor, run <prompt>, quota --status, " +
        "account-list, account-save, switch <account>, version. " +
        "Use for quota-aware agy delegation with automatic account rotation.",
      args: {
        command: tool.schema
          .string()
          .describe(
            "agykit subcommand: status, doctor, run, quota, account-list, " +
              "account-save, switch, version, init, help"
          ),
        args: tool.schema
          .string()
          .optional()
          .describe("Arguments passed to the subcommand"),
      },
      async execute({ command, args = "" }) {
        if (command === "run" && !args) {
          return "Usage: agykit run <prompt>\nProvide the prompt to delegate to agy.";
        }
        const output = runAgykit(command, args);
        return formatOutput(output);
      },
    }),
  },

  config: async (cfg) => {
    if (!cfg.agent) cfg.agent = {};
    if (!cfg.agent["agykit-run"]) {
      cfg.agent["agykit-run"] = {
        description:
          "Run a prompt through agykit with quota-aware account rotation",
        mode: "subagent",
        model: "9router/zekiler-bedava",
      };
    }
    if (!cfg.agent["agykit-escalate"]) {
      cfg.agent["agykit-escalate"] = {
        description:
          "Escalate a code task through agykit (Flash → Pro → Opus) with verify",
        mode: "subagent",
        model: "cc/claude-sonnet-4-6",
      };
    }
  },

  "tool.execute.after": async ({ tool: toolName }, { output }) => {
    if (toolName !== "agykit") return;
    if (
      /quota|rate\s*limit|429|insufficient|exhausted/i.test(output.output)
    ) {
      output.metadata = {
        ...(output.metadata || {}),
        agykit_quota_hit: true,
        tip: "Try: switch accounts (agykit account-list → agykit switch <name>) " +
          "or wait for quota reset.",
      };
    }
  },
});

export default AgykitPlugin;
