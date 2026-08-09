---
name: skill-analyzer
description: "Analyze and inventory all installed Codex skills and plugins. Scans ~/.codex/skills, ~/.codex/skills/.system, ~/.agents/skills, and ~/.codex/plugins directories, extracts metadata from YAML frontmatter and plugin.json, and produces structured reports in JSON, Markdown, and HTML. Use when the user asks to analyze installed skills/plugins, list all skills, get a skill inventory, review what's installed, 插件清单, 技能清单, 分析已安装的技能, 列出所有技能, /skill-analyzer. Does not install or modify skills — for that use skill-installer."
---

# Skill Analyzer

Analyze and inventory all installed Codex skills and plugins. Produce a clear, structured report showing each skill/plugin's name, description, source, triggers, and status.

## When to Use

- User asks "what skills do I have installed?"
- User asks to "analyze my skills and plugins"
- User asks for a "skill inventory" or "plugin list"
- User says "列出所有技能" / "插件清单" / "分析已安装的技能"

## How It Works

### Step 1: Run the scanner

Execute the bundled script to scan all standard Codex directories:

```bash
python scripts/analyze_skills.py --format json
```

This produces structured JSON with all skills/plugins categorized by source:
- **system** — built-in skills in `~/.codex/skills/.system/`
- **user_skills** — user-installed skills in `~/.codex/skills/` (`.git` presence marks GitHub-installed)
- **agents_skills** — skills in `~/.agents/skills/`
- **plugins** — plugins from `~/.codex/plugins/cache/` (with their bundled sub-skills)

### Step 2: Read and interpret the JSON

Read the JSON output. For each skill, extract and present:
- **Name** — from frontmatter `name` field
- **Description** — from frontmatter `description` field (collapsed to single line)
- **Source** — system / user / git (GitHub-installed) / agents / plugin
- **Triggers** — extracted trigger phrases from the description
- **Status** — active or ~~retired~~ (detected from "退役"/"retired" in description)

### Step 3: Enrich with AI interpretation

For fields the script cannot fully determine, add AI-derived context:
- **Applicable scenarios** — infer from the description what tasks the skill is designed for
- **Trigger conditions** — if the script extracted few triggers, re-read the full description to identify additional trigger phrases (especially Chinese keywords after "当用户说" or English keywords after "triggers on")
- **Relationships** — note related_skills from metadata if present

### Step 4: Present results

Present the analysis in two forms:

1. **Markdown tables** in chat — grouped by source category, with columns: Name | Description | Source | Triggers | Status
2. **HTML report file** — generate a browsable HTML page with:
   - Summary stats (counts per category)
   - Searchable/filterable skill cards
   - Plugin sections with sub-skill listings

To generate the HTML + Markdown files:

```bash
python scripts/analyze_skills.py --format all --output ./reports
```

## Script Options

```
--format json       Output JSON to stdout
--format markdown   Save Markdown report to file
--format html       Save HTML report to file
--format all        Save all three formats (default)
--codex-home PATH   Custom .codex directory
--output PATH       Output directory for files
```

## Edge Cases

- **Permission denied** (e.g., `global-biblio-base`): the script marks it as "(access denied or unreadable)" and continues
- **Retired skills** (e.g., `plan-report`): detected via "退役"/"retired" keyword in description, marked with ~~retired~~ badge
- **Plugins with version subdirectories**: the script descends into version dirs to find `plugin.json`
- **Skills with no frontmatter**: falls back to directory name as the skill name

## Example Session

```
User: 分析一下我已安装的 skills 和 plugins

AI: [runs script] → reads JSON → presents 4 Markdown tables grouped by source →
    generates HTML report → saves to reports/skill-inventory.html

    Found 56 skills across 4 sources:
    - 6 system built-in
    - 42 user skills (3 GitHub-installed)
    - 1 agents skill
    - 1 plugin (13 sub-skills)
```
