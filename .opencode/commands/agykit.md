---
description: Run a prompt through agykit with quota-aware account rotation and model-ladder escalation
---

# agykit

Delegates a prompt to agy via agykit (v1.4.0). Handles account rotation on quota errors, silence detection, model ladder escalation with verify, and job observability.

## Usage

```bash
agykit run "your prompt here"
agykit do-escalate "implement this feature"
agykit wait [job-id]
```

## When to use

- `agykit run` — explanation, analysis, Q&A, read-only tasks (no verify needed)
- `agykit do-escalate` — code changes that must pass `AGYKIT_VERIFY` (Flash → Pro → Opus)
- Never use plain `agy` directly — agykit handles rotation, silence detection, and fallback

## Pre-flight

```bash
agykit status          # active account | model | quota summary
agykit quota --status  # per-model remaining %
```

## Job tracking

```bash
agykit jobs            # recent jobs with status
agykit wait            # block until last job ends (exit 0=ok 1=fail 2=timeout)
agykit watch <job-id>  # live-stream events
```

## Update

```bash
agykit update          # pull latest version from git remote
```
