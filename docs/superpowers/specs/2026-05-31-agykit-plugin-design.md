# agykit Plugin Design

**Date:** 2026-05-31  
**Status:** Approved  
**Goal:** Package agykit as an installable Claude Code plugin — single `npm install -g agykit` installs the CLI and registers the plugin.

---

## Architecture

Single-repo approach (caveman pattern). Existing `agykit` bash+python codebase unchanged. New files added:

```
agykit/
├── package.json                  # npm package manifest
├── .claude-plugin/
│   └── plugin.json               # Claude Code hooks definition
├── skills/
│   └── agykit/
│       └── index.md              # agykit:delegate skill
├── src/
│   └── hooks/
│       └── session-start.js      # SessionStart hook
├── bin/
│   └── install.js                # Installer (Node.js, zero deps)
│
├── agykit                        # existing bash CLI (unchanged)
├── dashboard/                    # existing Python server (unchanged)
├── web/                          # existing frontend (unchanged)
└── tests/                        # existing tests (unchanged)
```

---

## Components

### 1. `package.json`

- Name: `agykit`
- Version: `1.0.0`
- Binary entry: `"agykit-install": "./bin/install.js"`
- Files: `bin/`, `src/`, `skills/`, `.claude-plugin/`, `agykit`, `dashboard/`, `web/`
- No runtime npm dependencies (zero-dep constraint preserved)
- Node.js ≥18 (for install only; runtime is bash+python)

### 2. `bin/install.js`

Runs on `npm install -g agykit`. Steps:

1. **Symlink CLI**: `~/.local/bin/agykit` → `{npm_package_root}/agykit`  
   - Falls back to `/usr/local/bin/agykit` if `~/.local/bin` not in PATH  
   - Skips if symlink already correct  
2. **Register plugin** in `~/.claude/plugins/installed_plugins.json`:  
   ```json
   "agykit@agykit": [{"scope":"user","installPath":"{package_root}","version":"{version}","installedAt":"..."}]
   ```
3. **Register marketplace** in `~/.claude/plugins/known_marketplaces.json`:  
   ```json
   "agykit": {"source":{"source":"github","repo":"{repo from package.json repository.url}"},"installLocation":"...","lastUpdated":"..."}
   ```
   GitHub repo URL `package.json`'daki `repository.url` alanından okunur.
4. Print success + next steps: `agykit account-save` → `agykit doctor`

Claude Code reads `installPath` → auto-loads `.claude-plugin/plugin.json`, `skills/`, hooks.

**Update path:** `npm update -g agykit` → symlink unchanged, package updated in place.

### 3. `.claude-plugin/plugin.json`

Hooks definition:

```json
{
  "name": "agykit",
  "description": "Quota-aware agy CLI manager — account rotation, model ladder, usage dashboard",
  "author": {"name": "Bmdersleri", "url": "https://github.com/Bmdersleri/agykit"},
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "node \"${CLAUDE_PLUGIN_ROOT}/src/hooks/session-start.js\"",
        "timeout": 3,
        "statusMessage": "Loading agykit context..."
      }]
    }]
  }
}
```

### 4. `src/hooks/session-start.js`

Runs on every SessionStart. Checks if `agykit` is in PATH:

- **Found**: prints one-line context reminder to stdout (becomes system-reminder):
  ```
  agykit available. /agykit:delegate "task" — auto-routes to run or do-escalate.
  Monitoring: agykit log | agykit dash | agykit quota
  ```
- **Not found**: prints install instruction and exits cleanly (no error)

Zero npm deps. Pure Node.js stdlib (`child_process.execSync`, `fs`, `os`).

### 5. `skills/agykit/index.md`

Skill ID: `agykit:delegate`  
Trigger: `/agykit:delegate` or when user asks to delegate a task via agykit

**Behavior:**

1. Check CWD for `.agykit.conf`
2. `.agykit.conf` exists → `agykit do-escalate "{prompt}"` (code task, verify active)
3. No `.agykit.conf` → `agykit run "{prompt}"` (simple query, quota-aware rotation)
4. Display output; note that result is in ops log (`agykit log`)

If `agykit` not in PATH: display install instructions instead of running.

---

## Data Flow

```
User: /agykit:delegate "implement X"
  │
  ▼
Skill checks .agykit.conf in CWD
  │
  ├─ exists → agykit do-escalate "implement X"
  │               │
  │               ▼
  │           git snapshot → agy runs → verify → (escalate if fail) → ops log
  │
  └─ missing → agykit run "implement X"
                   │
                   ▼
               account rotation → agy runs → ops log
```

---

## Error Handling

| Scenario | Behavior |
|---|---|
| `agykit` not in PATH | install.js exits with helpful message; session-start.js prints install hint |
| `~/.claude/plugins/` missing | install.js skips plugin registration, warns user |
| JSON parse failure (settings files) | install.js aborts that step, logs warning, continues |
| npm symlink target missing | install.js re-creates symlink |
| All accounts exhausted | agykit itself handles — logs to ops log, exits non-zero |

---

## Testing

- `bin/install.js --dry-run` flag: prints actions without writing files
- Existing bash test suite (`bash tests/run.sh`) unchanged
- Existing Python tests (`python3 -m pytest tests -q`) unchanged
- Manual: fresh install on Linux, verify symlink + Claude Code plugin loads

---

## Constraints Preserved

- Zero pip dependencies — runtime is still bash+python stdlib only
- `install.js` uses zero npm runtime deps (stdlib only)
- `agykit` bash script unchanged
- `127.0.0.1` only for dashboard
- Vanilla JS/HTML/CSS frontend unchanged

---

## Out of Scope

- Windows support (Linux/macOS only for now)
- MCP server integration
- Claude Code marketplace submission (future: submit to official registry)
- Auto-update mechanism beyond `npm update -g agykit`
