# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Educational project teaching AI agent architecture through 12 progressive Python sessions (s01-s12), paired with an interactive Next.js learning platform. Each session adds exactly one mechanism to a nano Claude Code-like agent, building from a simple loop to isolated autonomous multi-agent execution.

## Repository Layout

- `agents/` — 12 progressive Python agent implementations (`s01_*.py` through `s12_*.py`) plus `s_full.py` capstone
- `web/` — Next.js 16 interactive learning platform (React 19, Tailwind CSS 4)
- `docs/` — Mental-model documentation in en/zh/ja
- `skills/` — Reusable skill definitions loaded by s05

## Commands

### Python Agents

```bash
# Setup
cp .env.example .env  # then set ANTHROPIC_API_KEY and MODEL_ID
pip install -r requirements.txt

# Run any session
python agents/s01_agent_loop.py
python agents/s12_worktree_task_isolation.py
```

Environment variables: `ANTHROPIC_API_KEY` (required), `MODEL_ID` (required, e.g. `claude-sonnet-4-6`), `ANTHROPIC_BASE_URL` (optional, for compatible providers like MiniMax, GLM/Zhipu, Kimi, DeepSeek).

The capstone `s_full.py` supports REPL commands: `/compact`, `/tasks`, `/team`, `/inbox`.

### Web Platform

All web commands run from `web/`:

```bash
cd web
npm ci
npm run dev          # dev server (auto-runs extract script)
npm run build        # production build (static export)
npx tsc --noEmit     # type check
npm run extract      # manually regenerate versions.json + docs.json from Python sources
```

The `extract` script (`scripts/extract-content.ts`) parses Python agent files and generates `src/data/generated/versions.json` and `docs.json`. It runs automatically via `predev`/`prebuild` hooks. The generated files are not checked into git — they are rebuilt on every dev/build.

### CI

- **CI workflow**: type check + Next.js build (Node 20)
- **Test workflow**: `python tests/test_unit.py` for unit tests; session tests (`test_v0` through `test_v9`) run in parallel matrix with `TEST_API_KEY`, `TEST_BASE_URL`, `TEST_MODEL` secrets. Note: test files are referenced in CI but may not all exist yet.

## Architecture

### Agent Sessions — Progressive Layering

The core pattern is a while loop that sends messages to the LLM, executes any requested tools, appends results, and loops until `stop_reason != "tool_use"`. Each session adds one layer without changing this loop:

| Phase | Sessions | What's Added |
|-------|----------|-------------|
| The Loop | s01-s02 | Single tool, then tool dispatch map |
| Planning & Knowledge | s03-s06 | TodoManager, subagents, skill loading, context compression |
| Persistence | s07-s08 | File-based task graph with dependencies, background threads |
| Teams | s09-s12 | Teammates + mailboxes, protocols (FSM), autonomous task claiming, worktree isolation |

### Web Platform

- **Static Site Generation** — `output: "export"` in next.config.ts, deployed to Vercel
- **i18n** — Context-based system with `[locale]` dynamic route segments; 3 locales (en, zh, ja) with translation files in `src/i18n/messages/`
- **Data pipeline** — `extract-content.ts` reads Python source files at build time, extracts metadata/class definitions/diffs, outputs JSON consumed by React components. If agent Python files change, the web data must be regenerated.
- **Path alias** — `@/*` maps to `src/*` in tsconfig
- **Routes**: `/[locale]/` (home), `/[locale]/[version]` (session viewer), `/[locale]/[version]/diff`, `/[locale]/compare`, `/[locale]/timeline`, `/[locale]/layers`
- **Key constants** — `src/lib/constants.ts` defines `VERSION_META` and `LEARNING_PATH` mapping session IDs to metadata and layer categories
- **Visualizations** — Per-session interactive components in `src/components/visualizations/`
- **No linting configured** — only TypeScript type checking via `tsc --noEmit`

### Agent File Conventions

- Each agent file is self-contained with inline tool definitions and handlers
- Safety patterns: path validation (WORKDIR sandboxing), dangerous command blocking, tool timeouts (120s), output size limits (50KB)
- File-based state: `.team/config.json` for team config, `.team/inbox/*.jsonl` for per-agent mailboxes (append-only)
