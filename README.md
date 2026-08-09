# Skill Analyzer

Analyze and inventory all installed Codex skills and plugins.

Scans `~/.codex/skills/`, `~/.codex/skills/.system/`, `~/.agents/skills/`, and `~/.codex/plugins/` directories, extracts metadata from YAML frontmatter and `plugin.json`, and produces structured reports in **JSON**, **Markdown**, and **HTML**.

## What It Does

Give it one command and it scans your entire Codex installation:

```
56 skills found across 4 sources:
  - 6  system built-in
  - 42 user skills (3 GitHub-installed)
  - 1  agents skill
  - 1  plugin (13 sub-skills)
```

Each skill is catalogued with its name, description, source type, trigger keywords, and active/retired status.

## Installation

### Via skill-installer (recommended)

```
Install skill from github: zyiabc/skill-analyzer
```

### Manual

```bash
git clone https://github.com/zyiabc/skill-analyzer.git ~/.codex/skills/skill-analyzer
```

## Usage

### As a Codex Skill

Just ask:

> "分析一下我已安装的 skills 和 plugins"
> "Analyze my installed skills and plugins"

Codex will automatically run the scanner and present results in chat + generate an HTML report.

### Standalone CLI

```bash
# Output JSON to stdout
python scripts/analyze_skills.py --format json

# Generate Markdown + HTML + JSON files
python scripts/analyze_skills.py --format all --output ./reports

# Custom .codex home
python scripts/analyze_skills.py --codex-home /custom/path/.codex
```

### Options

| Flag | Description |
|---|---|
| `--format json` | Print JSON to stdout |
| `--format markdown` | Save Markdown report to file |
| `--format html` | Save HTML report to file |
| `--format all` | Save all three formats (default) |
| `--lang en` | English report, grouped by source (default) |
| `--lang zh` | Chinese report, grouped by application domain with deduplication |
| `--codex-home PATH` | Custom `.codex` directory |
| `--output PATH` | Output directory for report files |

### `--lang zh` Mode

Generates a Chinese HTML report with skills grouped by **application domain** instead of source directory:

- **Two-level categorization**: 大类 (domain) → 小类 (subcategory), e.g. 学术研究 → 论文写作
- **Deduplication**: skills installed in multiple directories are merged into one entry
- **Five-field cards**: 名称, 描述, 来源, 适用场景, 触发条件
- **Interactive**: live search + category filter pills
- **Auto-categorization**: keyword-based matching via `DOMAIN_MAP` (27 rules)

```bash
# Chinese domain-categorized report
python scripts/analyze_skills.py --format html --lang zh --output ./reports

# All formats in Chinese mode
python scripts/analyze_skills.py --format all --lang zh --output ./reports
```

## Output Formats

### JSON

Structured data for programmatic consumption — all skills grouped by source category with full metadata.

### Markdown

GitHub-renderable tables grouped by source: system, user, agents, plugins. Each table has columns: Name | Description | Source | Triggers | Status.

### HTML

A dark-themed, searchable single-page report.

**`--lang en` (default)**: Grouped by source (system / user / agents / plugins) with summary statistics dashboard and collapsible skill cards.

**`--lang zh`**: Grouped by application domain (学术研究 / 专利 / 产品与研发 / …) with:
- Two-level navigation (大类 → 小类) and category filter pills
- Five-field skill cards: 名称, 描述, 来源, 适用场景, 触发条件
- Cross-directory deduplication (same skill shown once)
- Retired skills visually de-emphasized

## How It Works

1. **Scans 4 source directories** — system built-ins, user skills, agents skills, and plugin cache
2. **Parses YAML frontmatter** from each `SKILL.md` (no PyYAML dependency — uses a lightweight regex parser)
3. **Reads `plugin.json`** for plugin metadata (name, version, author, repository, license)
4. **Detects source type** — `.git` directory presence marks GitHub-installed skills
5. **Extracts trigger keywords** from descriptions (quoted phrases, "triggers on" / "当用户说" patterns)
6. **Flags retired skills** — detects "退役" / "retired" in descriptions

## Requirements

- Python 3.8+ (standard library only — no pip install needed)
- Works on Windows, macOS, and Linux

## Project Structure

```
skill-analyzer/
├── SKILL.md              # Skill entry point (frontmatter + instructions)
├── agents/
│   └── openai.yaml       # UI metadata
├── scripts/
│   └── analyze_skills.py # Core scanner (Python, zero dependencies)
├── README.md
├── LICENSE
└── .gitignore
```

## License

MIT — see [LICENSE](LICENSE).

## Contributing

Issues and PRs welcome at [github.com/zyiabc/skill-analyzer](https://github.com/zyiabc/skill-analyzer).

