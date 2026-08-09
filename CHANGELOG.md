# Changelog

All notable changes to this project are documented in this file.

## [1.1.0] - 2026-08-09

### Added
- **`--lang zh` option** — generates a Chinese, domain-categorized HTML report
  - Groups skills by **application domain** (学术研究, 专利, 产品与研发, 写作与内容, 设计与视觉, 思维与决策, Web与信息检索, 软件开发与协作, 教学与课程, 系统与工具, 角色与趣味, 已退役) instead of by source directory
  - Two-level structure: 大类 → 小类 for quick navigation
  - Each skill card displays five fields: 名称, 描述, 来源 (colored badge), 适用场景, 触发条件
  - Built-in **keyword-based auto-categorization** (`DOMAIN_MAP`) with 27 domain→subcategory rules
  - **Deduplication** — skills with the same name across multiple source directories (e.g. `agent-reach` in both `~/.codex/skills` and `~/.agents/skills`) are merged into a single entry
  - Interactive **search bar** and **category filter pills** with live filtering
  - Dark theme with responsive card grid layout
  - Retired skills (检测 "退役"/"retired") are visually de-emphasized with strikethrough and 55% opacity
- `skill-inventory-zh.html` output file when using `--format all --lang zh`

### Changed
- `--lang` defaults to `en` (existing English, source-based report) — fully backward compatible

### Fixed
- Duplicate skills appearing in reports when the same skill is installed in multiple directories

## [1.0.0] - 2026-08-08

### Initial Release
- Scans `~/.codex/skills/`, `~/.codex/skills/.system/`, `~/.agents/skills/`, and `~/.codex/plugins/`
- Extracts metadata from YAML frontmatter and `plugin.json`
- Detects source type (system / user / git / agents / plugin)
- Extracts trigger keywords from descriptions
- Flags retired skills ("退役" / "retired")
- Outputs JSON, Markdown, and HTML reports
- Zero dependencies — Python 3.8+ standard library only
