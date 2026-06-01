---
description: Run a prompt through agykit with quota-aware account rotation
---

# agykit

Delegates a prompt to agy via agykit. Handles account rotation on quota errors,
model selection, and optional verify step.

## Usage

```bash
agykit run "your prompt here"
agykit do-escalate "implement this feature"
```

## When to use

- `agykit run` — explanation, analysis, Q&A, simple code changes without verify
- `agykit do-escalate` — code changes that must pass `AGYKIT_VERIFY`
- Never use plain `agy` directly — agykit handles rotation and fallback

## Pre-flight

```bash
agykit status          # active account | model | quota
agykit quota --status  # per-model remaining %
```
