#!/usr/bin/env python3
"""Analyze installed Codex skills and plugins.

Scans standard Codex directories for skills and plugins, extracts metadata
from YAML frontmatter and plugin.json, and outputs structured reports.

Usage:
    python analyze_skills.py                  # default: markdown + html
    python analyze_skills.py --format json    # JSON to stdout
    python analyze_skills.py --format markdown
    python analyze_skills.py --format html
    python analyze_skills.py --codex-home /path/to/.codex
    python analyze_skills.py --output ./reports
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# YAML frontmatter parser (no PyYAML dependency)
# ---------------------------------------------------------------------------

def parse_frontmatter(text):
    """Extract YAML frontmatter from markdown text. Returns a dict."""
    fm = {}
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return fm
    raw = match.group(1)
    # Parse simple key: value lines, plus multiline values (|, >, and bare >)
    lines = raw.split("\n")
    current_key = None
    current_val = []
    multiline_indicator = None

    def flush():
        nonlocal current_key, current_val, multiline_indicator
        if current_key:
            val = "\n".join(current_val).strip()
            if multiline_indicator in ("|", ">"):
                fm[current_key] = val
            elif multiline_indicator == "bare":
                fm[current_key] = val
            else:
                fm[current_key] = val
            current_key = None
            current_val = []
            multiline_indicator = None

    for line in lines:
        kv = re.match(r"^(\w[\w\-]*)\s*:\s*(.*)$", line)
        if kv and not line.startswith(" ") and not line.startswith("\t"):
            flush()
            current_key = kv.group(1)
            value = kv.group(2).strip()
            if value == "|":
                multiline_indicator = "|"
            elif value == ">":
                multiline_indicator = ">"
            elif value == "":
                multiline_indicator = "bare"
            else:
                # Strip quotes if present
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                fm[current_key] = value
                current_key = None
        elif current_key:
            current_val.append(line)
    flush()
    return fm


def extract_triggers(description):
    """Extract trigger keywords from a skill description."""
    if not description:
        return []
    triggers = []
    # Match Chinese trigger phrases in quotes
    quoted = re.findall(r'["\u201c\u201d]([^"\u201c\u201d]{2,80})["\u201c\u201d]', description)
    triggers.extend(quoted)
    # Match phrases after "when user says" or "triggers on" or "当用户说"
    say_match = re.findall(
        r'(?:when user says|triggers? on|当用户说[^，。]*?["\u201c])([^。，;]+?)(?:["\u201d]|$)',
        description, re.IGNORECASE,
    )
    triggers.extend(say_match)
    # Deduplicate, keep order
    seen = set()
    result = []
    for t in triggers:
        t = t.strip().strip('"').strip("\u201c").strip("\u201d")
        if t and t not in seen and len(t) > 1:
            seen.add(t)
            result.append(t)
    return result


# ---------------------------------------------------------------------------
# Scanners
# ---------------------------------------------------------------------------

def scan_skill_md(skill_dir):
    """Read and parse a SKILL.md file. Returns dict or None on error."""
    skill_md = os.path.join(skill_dir, "SKILL.md")
    try:
        with open(skill_md, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except (PermissionError, OSError):
        return None
    fm = parse_frontmatter(text)
    name = fm.get("name", os.path.basename(skill_dir))
    description = fm.get("description", "")
    # Clean description: collapse whitespace
    if description:
        description = re.sub(r"\s+", " ", description).strip()
    has_git = os.path.isdir(os.path.join(skill_dir, ".git"))
    is_retired = "退役" in description or "retired" in description.lower()
    return {
        "name": name,
        "description": description,
        "triggers": extract_triggers(description),
        "source_dir": skill_dir,
        "has_git": has_git,
        "retired": is_retired,
        "version": fm.get("version", ""),
        "metadata": {k: v for k, v in fm.items()
                      if k not in ("name", "description", "version")},
    }


def scan_plugin(plugin_dir):
    """Scan a plugin directory: read plugin.json + sub-skills."""
    plugin_json_path = os.path.join(plugin_dir, ".codex-plugin", "plugin.json")
    try:
        with open(plugin_json_path, "r", encoding="utf-8") as f:
            pj = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError):
        return None
    plugin = {
        "name": pj.get("name", os.path.basename(plugin_dir)),
        "description": pj.get("description", pj.get("interface", {}).get("longDescription", "")),
        "version": pj.get("version", ""),
        "repository": pj.get("repository", ""),
        "author": pj.get("author", {}).get("name", "") if isinstance(pj.get("author"), dict) else str(pj.get("author", "")),
        "homepage": pj.get("homepage", ""),
        "license": pj.get("license", ""),
        "source_dir": plugin_dir,
        "source_type": "plugin",
        "skills": [],
    }
    # Scan sub-skills
    skills_subdir = pj.get("skills", "./skills/")
    skills_path = os.path.join(plugin_dir, skills_subdir)
    if os.path.isdir(skills_path):
        for entry in sorted(os.listdir(skills_path)):
            entry_path = os.path.join(skills_path, entry)
            if os.path.isdir(entry_path) and os.path.isfile(os.path.join(entry_path, "SKILL.md")):
                skill = scan_skill_md(entry_path)
                if skill:
                    skill["source_type"] = "plugin-skill"
                    skill["parent_plugin"] = plugin["name"]
                    plugin["skills"].append(skill)
    return plugin


def scan_all(codex_home=None, agents_home=None):
    """Scan all standard directories. Returns structured data."""
    if codex_home is None:
        codex_home = os.path.join(os.path.expanduser("~"), ".codex")
    if agents_home is None:
        agents_home = os.path.join(os.path.expanduser("~"), ".agents")

    skills_dir = os.path.join(codex_home, "skills")
    system_dir = os.path.join(skills_dir, ".system")
    agents_skills_dir = os.path.join(agents_home, "skills")
    plugins_cache_dir = os.path.join(codex_home, "plugins", "cache")

    result = {
        "scan_time": datetime.now().isoformat(timespec="seconds"),
        "codex_home": codex_home,
        "categories": {
            "system": [],
            "user_skills": [],
            "agents_skills": [],
            "plugins": [],
        },
    }

    # 1. System built-in skills
    if os.path.isdir(system_dir):
        for entry in sorted(os.listdir(system_dir)):
            entry_path = os.path.join(system_dir, entry)
            if os.path.isdir(entry_path) and os.path.isfile(os.path.join(entry_path, "SKILL.md")):
                skill = scan_skill_md(entry_path)
                if skill:
                    skill["source_type"] = "system"
                    result["categories"]["system"].append(skill)

    # 2. User skills (exclude .system)
    if os.path.isdir(skills_dir):
        for entry in sorted(os.listdir(skills_dir)):
            if entry == ".system":
                continue
            entry_path = os.path.join(skills_dir, entry)
            if os.path.isdir(entry_path) and os.path.isfile(os.path.join(entry_path, "SKILL.md")):
                skill = scan_skill_md(entry_path)
                if skill:
                    skill["source_type"] = "git" if skill["has_git"] else "user"
                    result["categories"]["user_skills"].append(skill)
                elif skill is None:
                    # Permission denied or read error
                    result["categories"]["user_skills"].append({
                        "name": entry,
                        "description": "(access denied or unreadable)",
                        "triggers": [],
                        "source_dir": entry_path,
                        "has_git": False,
                        "retired": False,
                        "source_type": "user",
                    })

    # 3. Agents skills
    if os.path.isdir(agents_skills_dir):
        for entry in sorted(os.listdir(agents_skills_dir)):
            entry_path = os.path.join(agents_skills_dir, entry)
            if os.path.isdir(entry_path) and os.path.isfile(os.path.join(entry_path, "SKILL.md")):
                skill = scan_skill_md(entry_path)
                if skill:
                    skill["source_type"] = "agents"
                    result["categories"]["agents_skills"].append(skill)

    # 4. Plugins
    if os.path.isdir(plugins_cache_dir):
        for source in sorted(os.listdir(plugins_cache_dir)):
            source_path = os.path.join(plugins_cache_dir, source)
            if not os.path.isdir(source_path):
                continue
            for plugin_name in sorted(os.listdir(source_path)):
                plugin_path = os.path.join(source_path, plugin_name)
                if not os.path.isdir(plugin_path):
                    continue
                # Plugins may have version subdirectories
                for sub in sorted(os.listdir(plugin_path)):
                    sub_path = os.path.join(plugin_path, sub)
                    if os.path.isdir(sub_path) and os.path.isfile(
                        os.path.join(sub_path, ".codex-plugin", "plugin.json")
                    ):
                        plugin = scan_plugin(sub_path)
                        if plugin:
                            plugin["marketplace"] = source
                            result["categories"]["plugins"].append(plugin)
                    elif os.path.isfile(os.path.join(plugin_path, ".codex-plugin", "plugin.json")):
                        plugin = scan_plugin(plugin_path)
                        if plugin:
                            plugin["marketplace"] = source
                            result["categories"]["plugins"].append(plugin)

    # Compute totals
    result["totals"] = {
        "system": len(result["categories"]["system"]),
        "user_skills": len(result["categories"]["user_skills"]),
        "agents_skills": len(result["categories"]["agents_skills"]),
        "plugins": len(result["categories"]["plugins"]),
        "plugin_skills": sum(len(p.get("skills", [])) for p in result["categories"]["plugins"]),
    }
    result["totals"]["grand_total"] = (
        result["totals"]["system"]
        + result["totals"]["user_skills"]
        + result["totals"]["agents_skills"]
        + result["totals"]["plugin_skills"]
        + result["totals"]["plugins"]
    )
    return result


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def to_json(data):
    return json.dumps(data, indent=2, ensure_ascii=False)


def md_escape(text):
    """Escape pipe characters for markdown tables."""
    if not text:
        return ""
    text = str(text)
    text = text.replace("|", "\\|")
    text = text.replace("\n", " ")
    if len(text) > 150:
        text = text[:147] + "..."
    return text


def to_markdown(data):
    lines = []
    cat = data["categories"]
    totals = data["totals"]

    lines.append("# Codex Skills & Plugins Inventory\n")
    lines.append(f"_Scanned: {data['scan_time']}_\n")

    lines.append("## Summary\n")
    lines.append("| Source | Count |")
    lines.append("|---|---|")
    lines.append(f"| System built-in | {totals['system']} |")
    lines.append(f"| User skills | {totals['user_skills']} |")
    lines.append(f"| Agents skills | {totals['agents_skills']} |")
    lines.append(f"| Plugins | {totals['plugins']} ({totals['plugin_skills']} sub-skills) |")
    lines.append(f"| **Grand total** | **{totals['grand_total']}** |")
    lines.append("")

    def skill_table(skills, title):
        lines.append(f"## {title}\n")
        if not skills:
            lines.append("_None found._\n")
            return
        lines.append("| Name | Description | Source | Triggers | Status |")
        lines.append("|---|---|---|---|---|")
        for s in skills:
            src = s.get("source_type", "")
            retired = "~~retired~~" if s.get("retired") else "active"
            triggers = ", ".join(s.get("triggers", [])[:5])
            lines.append(
                f"| `{s['name']}` | {md_escape(s['description'])} | {src} | {md_escape(triggers)} | {retired} |"
            )
        lines.append("")

    def plugin_section(plugins, title):
        lines.append(f"## {title}\n")
        if not plugins:
            lines.append("_None found._\n")
            return
        for p in plugins:
            lines.append(f"### {p['name']} (v{p.get('version', '?')})\n")
            lines.append(f"- **Description**: {md_escape(p['description'])}")
            lines.append(f"- **Repository**: {p.get('repository', 'N/A')}")
            lines.append(f"- **Author**: {p.get('author', 'N/A')}")
            lines.append(f"- **License**: {p.get('license', 'N/A')}")
            lines.append(f"- **Marketplace**: {p.get('marketplace', 'N/A')}")
            lines.append(f"- **Sub-skills**: {len(p.get('skills', []))}")
            lines.append("")
            if p.get("skills"):
                lines.append("| Name | Description | Triggers |")
                lines.append("|---|---|---|")
                for s in p["skills"]:
                    triggers = ", ".join(s.get("triggers", [])[:5])
                    lines.append(
                        f"| `{s['name']}` | {md_escape(s['description'])} | {md_escape(triggers)} |"
                    )
                lines.append("")

    skill_table(cat["system"], "System Built-in Skills")
    skill_table(cat["user_skills"], "User Skills")
    skill_table(cat["agents_skills"], "Agents Skills")
    plugin_section(cat["plugins"], "Plugins")
    return "\n".join(lines)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Codex Skills & Plugins Inventory</title>
<style>
:root {{
  --bg: #0d1117;
  --card: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --muted: #8b949e;
  --accent: #58a6ff;
  --green: #3fb950;
  --yellow: #d29922;
  --red: #f85149;
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  background: var(--bg); color: var(--text); margin: 0; padding: 0;
  line-height: 1.6;
}}
.container {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px 80px; }}
h1 {{ font-size: 1.8em; border-bottom: 1px solid var(--border); padding-bottom: 12px; }}
h2 {{ font-size: 1.4em; margin-top: 40px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
h3 {{ font-size: 1.15em; margin-top: 28px; color: var(--accent); }}
.summary {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 20px 0; }}
.stat {{
  background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 16px 24px; text-align: center; min-width: 140px;
}}
.stat .num {{ font-size: 2em; font-weight: 700; color: var(--accent); }}
.stat .label {{ font-size: 0.85em; color: var(--muted); margin-top: 4px; }}
.search-bar {{
  width: 100%; padding: 12px 16px; background: var(--card);
  border: 1px solid var(--border); border-radius: 8px; color: var(--text);
  font-size: 1em; margin: 20px 0; outline: none;
}}
.search-bar:focus {{ border-color: var(--accent); }}
.skill-card {{
  background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 16px 20px; margin-bottom: 12px; cursor: pointer;
  transition: border-color 0.2s;
}}
.skill-card:hover {{ border-color: var(--accent); }}
.skill-card .name {{ font-weight: 600; font-size: 1.05em; color: var(--text); }}
.skill-card .name code {{ background: #1f2937; padding: 2px 8px; border-radius: 4px; font-size: 0.95em; }}
.skill-card .desc {{ color: var(--muted); margin-top: 6px; font-size: 0.9em; }}
.badge {{
  display: inline-block; font-size: 0.75em; padding: 2px 10px; border-radius: 12px;
  margin-left: 8px; font-weight: 500; vertical-align: middle;
}}
.badge-system {{ background: #1a3a5c; color: var(--accent); }}
.badge-user {{ background: #2a2616; color: var(--yellow); }}
.badge-git {{ background: #1e2e1e; color: var(--green); }}
.badge-plugin {{ background: #3b1e3b; color: #d2a8e0; }}
.badge-retired {{ background: #3b1616; color: var(--red); }}
.triggers {{ margin-top: 8px; }}
.trigger-tag {{
  display: inline-block; background: #1f2937; color: var(--muted);
  font-size: 0.78em; padding: 2px 8px; border-radius: 4px; margin: 2px 4px 2px 0;
}}
.plugin-meta {{ margin-top: 8px; font-size: 0.85em; color: var(--muted); }}
.plugin-meta a {{ color: var(--accent); text-decoration: none; }}
.plugin-meta a:hover {{ text-decoration: underline; }}
.scan-info {{ color: var(--muted); font-size: 0.85em; }}
.hidden {{ display: none; }}
</style>
</head>
<body>
<div class="container">
<h1>⚡ Codex Skills &amp; Plugins Inventory</h1>
<p class="scan-info">Scanned: {scan_time} · Codex Home: <code>{codex_home}</code></p>

<div class="summary">
  <div class="stat"><div class="num">{n_system}</div><div class="label">System Built-in</div></div>
  <div class="stat"><div class="num">{n_user}</div><div class="label">User Skills</div></div>
  <div class="stat"><div class="num">{n_agents}</div><div class="label">Agents Skills</div></div>
  <div class="stat"><div class="num">{n_plugins}</div><div class="label">Plugins ({n_plugin_skills} sub-skills)</div></div>
  <div class="stat"><div class="num">{n_total}</div><div class="label">Grand Total</div></div>
</div>

<input class="search-bar" type="text" placeholder="🔍 Search skills by name, description, or trigger..." id="searchInput" oninput="filterCards()">

{sections}
</div>
<script>
function filterCards() {{
  const q = document.getElementById('searchInput').value.toLowerCase();
  document.querySelectorAll('.skill-card').forEach(card => {{
    const text = card.textContent.toLowerCase();
    card.classList.toggle('hidden', !text.includes(q));
  }});
}}
</script>
</body>
</html>"""


def skill_cards_html(skills):
    cards = []
    for s in skills:
        src = s.get("source_type", "user")
        badge_class = {
            "system": "badge-system",
            "user": "badge-user",
            "git": "badge-git",
            "agents": "badge-user",
            "plugin-skill": "badge-plugin",
        }.get(src, "badge-user")
        retired_badge = '<span class="badge badge-retired">retired</span>' if s.get("retired") else ""
        triggers_html = "".join(
            f'<span class="trigger-tag">{t}</span>' for t in s.get("triggers", [])[:8]
        )
        desc = s.get("description", "")
        if len(desc) > 200:
            desc = desc[:197] + "..."
        cards.append(f"""
<div class="skill-card">
  <div class="name"><code>{s['name']}</code><span class="badge {badge_class}">{src}</span>{retired_badge}</div>
  <div class="desc">{desc}</div>
  {f'<div class="triggers">{triggers_html}</div>' if triggers_html else ''}
</div>""")
    return "\n".join(cards)


def plugin_html(plugins):
    sections = []
    for p in plugins:
        repo_link = f'<a href="{p["repository"]}" target="_blank">{p["repository"]}</a>' if p.get("repository") else "N/A"
        sub_skills = p.get("skills", [])
        cards = skill_cards_html(sub_skills)
        sections.append(f"""
<h3>🔌 {p['name']} <span style="color:var(--muted);font-size:0.8em;">v{p.get('version', '?')}</span></h3>
<div class="plugin-meta">
  {p.get('description', '')}<br>
  <strong>Repo:</strong> {repo_link} · <strong>Author:</strong> {p.get('author', 'N/A')} · <strong>License:</strong> {p.get('license', 'N/A')} · <strong>Marketplace:</strong> {p.get('marketplace', 'N/A')} · <strong>Sub-skills:</strong> {len(sub_skills)}
</div>
{f'<div style="margin-top:12px;">{cards}</div>' if cards else ''}""")
    return "\n".join(sections)


def to_html(data):
    cat = data["categories"]
    t = data["totals"]

    def section(title, skills):
        cards = skill_cards_html(skills)
        return f"\n<h2>{title} ({len(skills)})</h2>\n{cards}" if cards else f"\n<h2>{title} (0)</h2>\n<p style='color:var(--muted);'>None found.</p>"

    sections = []
    sections.append(section("System Built-in Skills", cat["system"]))
    sections.append(section("User Skills", cat["user_skills"]))
    sections.append(section("Agents Skills", cat["agents_skills"]))
    sections.append(f"\n<h2>Plugins ({t['plugins']})</h2>\n{plugin_html(cat['plugins'])}" if cat["plugins"] else "\n<h2>Plugins (0)</h2>\n<p style='color:var(--muted);'>None found.</p>")

    return HTML_TEMPLATE.format(
        scan_time=data["scan_time"],
        codex_home=data["codex_home"],
        n_system=t["system"],
        n_user=t["user_skills"],
        n_agents=t["agents_skills"],
        n_plugins=t["plugins"],
        n_plugin_skills=t["plugin_skills"],
        n_total=t["grand_total"],
        sections="".join(sections),
    )


# ---------------------------------------------------------------------------
# Chinese domain-categorized HTML report (--lang zh)
# ---------------------------------------------------------------------------

import html as _html
from collections import OrderedDict as _OD

DOMAIN_MAP = [
    ("\u5b66\u672f\u7814\u7a76", "\u8c03\u7814\u4e0e\u6587\u732e\u68c0\u7d22", ["deep-research", "system-study", "agent-reach", "\u8c03\u7814", "research", "\u6587\u732e", "\u5b66\u4e60\u6750\u6599"]),
    ("\u5b66\u672f\u7814\u7a76", "\u6848\u4f8b\u4e0e\u751f\u6001\u626b\u63cf", ["case-radar", "\u6848\u4f8b", "\u751f\u6001\u626b\u63cf", "\u771f\u7269"]),
    ("\u5b66\u672f\u7814\u7a76", "\u8bba\u6587\u5199\u4f5c", ["academic-paper", "academic-pipeline", "\u8bba\u6587", "paper", "rebuttal", "citation"]),
    ("\u5b66\u672f\u7814\u7a76", "\u8bba\u6587\u8bc4\u5ba1", ["academic-paper-reviewer", "peer review", "referee", "\u8bc4\u5ba1", "critique"]),
    ("\u4e13\u5229", "\u4e13\u5229\u68c0\u7d22\u4e0e\u5206\u6790", ["google-patent-search", "patent-opportunity", "\u4e13\u5229\u68c0\u7d22", "BigQuery"]),
    ("\u4e13\u5229", "\u4e13\u5229\u64b0\u5199", ["patent-disclosure", "\u4ea4\u5e95\u4e66", "disclosure", "\u4e13\u5229\u67e5\u65b0"]),
    ("\u4ea7\u54c1\u4e0e\u7814\u53d1", "\u9700\u6c42\u5b9a\u4e49", ["prd-doc-writer", "prd-test-writer", "backlog-manager", "issue-pool", "goal-setter", "\u9700\u6c42", "PRD", "issue", "goal contract"]),
    ("\u4ea7\u54c1\u4e0e\u7814\u53d1", "\u7248\u672c\u89c4\u5212", ["version-planner", "vision-exploration", "\u7248\u672c", "\u613f\u666f", "MVP", "vision"]),
    ("\u4ea7\u54c1\u4e0e\u7814\u53d1", "\u9700\u6c42\u53d8\u66f4", ["req-change-workflow", "\u9700\u6c42\u53d8\u66f4", "change workflow", "\u91cd\u6784\u6d41\u7a0b"]),
    ("\u4ea7\u54c1\u4e0e\u7814\u53d1", "\u6d4b\u8bd5\u7f16\u6392", ["prd-auto-test-loop", "\u6d4b\u8bd5\u7f16\u6392", "test loop", "\u81ea\u52a8\u5316\u6d4b\u8bd5"]),
    ("\u4ea7\u54c1\u4e0e\u7814\u53d1", "\u53d1\u5e03\u7ba1\u7406", ["release", "changelog", "\u53d1\u5e03", "\u53d1\u7248"]),
    ("\u5199\u4f5c\u4e0e\u5185\u5bb9", "\u5199\u4f5c\u8f85\u52a9", ["writing-assistant", "thought-mining", "readable-output", "\u5199\u4f5c", "\u6316\u6398", "\u9009\u9898"]),
    ("\u5199\u4f5c\u4e0e\u5185\u5bb9", "\u62a5\u544a\u4e0e\u6da6\u8272", ["weekly-report", "humanizer", "image-assistant", "\u5468\u62a5", "\u6da6\u8272", "\u914d\u56fe", "AI \u5473"]),
    ("\u5199\u4f5c\u4e0e\u5185\u5bb9", "\u547d\u540d", ["product-naming", "\u547d\u540d", "naming", "\u8d77\u540d"]),
    ("\u8bbe\u8ba1\u4e0e\u89c6\u89c9", "\u754c\u9762\u8bbe\u8ba1", ["design-exploration", "ui-design", "macos-product-design", "\u754c\u9762\u8bbe\u8ba1", "UI \u6837\u5f0f", "macOS", "\u539f\u578b"]),
    ("\u8bbe\u8ba1\u4e0e\u89c6\u89c9", "\u56fe\u50cf\u751f\u6210", ["imagegen", "bitmap", "\u4f4d\u56fe", "raster", "\u63d2\u753b"]),
    ("\u601d\u7ef4\u4e0e\u51b3\u7b56", "\u601d\u7ef4\u534f\u4f5c", ["thinking-partner", "find-top-three", "priority-judge", "multi-perspective", "\u601d\u8003", "\u4f18\u5148\u7ea7", "\u591a\u89c6\u89d2", "\u8bca\u65ad"]),
    ("\u601d\u7ef4\u4e0e\u51b3\u7b56", "\u81ea\u4e3b\u6267\u884c", ["auto-task", "\u81ea\u4e3b\u6267\u884c", "\u957f\u7a0b\u4efb\u52a1", "\u4efb\u52a1\u961f\u5217"]),
    ("Web\u4e0e\u4fe1\u606f\u68c0\u7d22", "\u641c\u7d22\u4e0e\u53d1\u73b0", ["insane-search", "github-repo-search", "find-skills", "\u88ab\u5899", "\u5f00\u6e90\u9879\u76ee", "find a skill"]),
    ("Web\u4e0e\u4fe1\u606f\u68c0\u7d22", "Web\u667a\u80fd", ["wigolo", "web intelligence", "\u722c\u53d6", "\u6293\u53d6", "crawl", "fetch"]),
    ("\u8f6f\u4ef6\u5f00\u53d1\u4e0e\u534f\u4f5c", "Git\u4e0e\u591aAgent\u534f\u4f5c", ["git-push", "dual-agent", "\u63a8\u9001", "GitHub", "\u534f\u4f5c\u95ed\u73af", "\u4ea4\u53c9\u6821\u6838"]),
    ("\u8f6f\u4ef6\u5f00\u53d1\u4e0e\u534f\u4f5c", "\u5f00\u53d1\u65b9\u6cd5\u8bba\uff08superpowers \u63d2\u4ef6\uff09", ["brainstorming", "dispatching-parallel", "executing-plans", "finishing-a-development", "receiving-code-review", "requesting-code-review", "subagent-driven", "systematic-debugging", "test-driven", "using-git-worktrees", "using-superpowers", "verification-before", "writing-plans", "writing-skills"]),
    ("\u6559\u5b66\u4e0e\u8bfe\u7a0b", "\u8bfe\u7a0b\u5236\u4f5c", ["lesson-builder", "\u5907\u8bfe", "\u8bfe\u4ef6", "\u8bfe\u7a0b"]),
    ("\u7cfb\u7edf\u4e0e\u5de5\u5177", "\u6280\u80fd\u4e0e\u63d2\u4ef6\u7ba1\u7406", ["skill-creator", "skill-installer", "skill-analyzer", "plugin-creator", "\u521b\u5efa skill", "\u5b89\u88c5 skill", "scaffold plugin"]),
    ("\u7cfb\u7edf\u4e0e\u5de5\u5177", "\u6587\u6863\u4e0e\u5ba1\u67e5", ["openai-docs", "review-agent", "OpenAI", "\u4ee3\u7801\u5ba1\u67e5", "review"]),
    ("\u7cfb\u7edf\u4e0e\u5de5\u5177", "\u6574\u7406\u4e0e\u8bb0\u5fc6", ["organize", "memory-init", "project-map-builder", "\u6574\u7406\u6587\u4ef6", "\u8bb0\u5fc6\u7cfb\u7edf", "\u76ee\u5f55\u5730\u56fe"]),
    ("\u89d2\u8272\u4e0e\u8da3\u5473", "\u4eba\u8bbe\u4e0e\u5ba0\u7269", ["hermes-persona", "hatch-pet", "\u4eba\u8bbe", "\u5ba0\u7269", "persona", "animated pet"]),
]

_ZH_SRC = {"system": ("\u7cfb\u7edf\u5185\u7f6e", "#3b82f6"), "user": ("\u7528\u6237\u5b89\u88c5", "#22c55e"), "git": ("GitHub\u5b89\u88c5", "#a855f7"), "agents": ("Agents", "#f59e0b"), "plugin": ("\u63d2\u4ef6", "#14b8a6"), "plugin-skill": ("\u63d2\u4ef6", "#14b8a6")}


def _categorize_skill(skill):
    """Return (domain, subcategory) for a skill based on keyword matching."""
    if skill.get("retired"):
        return ("\u5df2\u9000\u5f79", "\u5df2\u9000\u5f71")
    name = (skill.get("name") or "").lower()
    desc = (skill.get("description") or "").lower()
    text = name + " " + desc
    for domain, sub, keywords in DOMAIN_MAP:
        for kw in keywords:
            if kw.lower() in text:
                return (domain, sub)
    return ("\u5176\u4ed6", "\u672a\u5206\u7c7b")


def _dedupe_skills(all_skills):
    """Deduplicate skills by name, keeping the first occurrence."""
    seen = set()
    result = []
    for s in all_skills:
        nm = s.get("name", "")
        if nm in seen:
            continue
        seen.add(nm)
        result.append(s)
    return result


def _infer_scene(name, desc):
    """Infer a short applicable-scenario string from the description."""
    if "\u5f53\u7528\u6237\u8bf4" in desc or "\u5f53\u7528\u6237" in desc:
        idx = desc.find("\u5f53\u7528\u6237")
        return desc[idx:idx+60].split("\u3002")[0].split(",")[0]
    d = desc.lower()
    if "use when" in d:
        idx = d.find("use when")
        return desc[idx:idx+80].split(".")[0]
    if "must use" in d:
        idx = d.find("must use")
        return desc[idx:idx+80].split(".")[0]
    return desc[:60] + ("..." if len(desc) > 60 else "")


_ZH_CSS = """:root{--bg:#0f172a;--surface:#1e293b;--border:#475569;--text:#e2e8f0;--dim:#94a3b8;--accent:#38bdf8;--accent2:#818cf8}*{box-sizing:border-box;margin:0;padding:0}body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text);line-height:1.6}.header{position:sticky;top:0;z-index:100;background:rgba(15,23,42,.95);backdrop-filter:blur(8px);border-bottom:1px solid var(--border);padding:18px 32px 14px}.header h1{font-size:22px;font-weight:700;margin-bottom:4px}.header .meta{font-size:13px;color:var(--dim);margin-bottom:12px}.chips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}.chip{font-size:12px;padding:3px 12px;border:1px solid;border-radius:999px;font-weight:600}.search-box{width:100%;padding:10px 16px;font-size:14px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text);outline:none}.search-box:focus{border-color:var(--accent)}.nav-bar{display:flex;gap:8px;flex-wrap:wrap;padding:14px 32px;border-bottom:1px solid var(--border);background:var(--surface);position:sticky;top:138px;z-index:90}.nav-pill{padding:6px 16px;border-radius:999px;border:1px solid var(--border);background:transparent;color:var(--dim);cursor:pointer;font-size:13px;transition:all .15s}.nav-pill:hover{border-color:var(--accent);color:var(--accent)}.nav-pill.active{background:var(--accent);color:var(--bg);border-color:var(--accent);font-weight:600}.nav-pill .count{font-size:11px;opacity:.7}.main{padding:24px 32px 60px;max-width:1400px;margin:0 auto}.cat-section{margin-bottom:40px}.cat-title{font-size:20px;font-weight:700;padding-bottom:8px;border-bottom:2px solid var(--accent2);margin-bottom:16px}.cat-count{font-size:14px;color:var(--dim);font-weight:400}.sub-group{margin-bottom:24px}.sub-title{font-size:15px;font-weight:600;color:var(--accent);margin-bottom:12px;padding-left:10px;border-left:3px solid var(--accent)}.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:14px}.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px;transition:border-color .15s,transform .1s}.card:hover{border-color:var(--accent);transform:translateY(-1px)}.card.retired{opacity:.55}.card-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px}.skill-name{font-size:15px;font-weight:700;color:var(--accent);background:rgba(56,189,248,.1);padding:2px 8px;border-radius:4px}.retired-name{font-size:15px;font-weight:700;color:var(--dim);text-decoration:line-through}.badge{font-size:11px;padding:2px 8px;border-radius:4px;color:#fff;font-weight:600;white-space:nowrap}.plugin-tag{font-size:11px;padding:2px 8px;border-radius:4px;background:rgba(20,184,166,.15);color:#2dd4bf;border:1px solid rgba(20,184,166,.3)}.card-body{display:flex;flex-direction:column;gap:6px}.field{display:flex;gap:8px;font-size:13px}.field-label{flex-shrink:0;width:56px;color:var(--dim);font-weight:600}.field-val{color:var(--text);flex:1}.field-val.trig{color:var(--accent2);font-size:12px}.empty{text-align:center;padding:60px;color:var(--dim);font-size:16px;display:none}@media(max-width:768px){.card-grid{grid-template-columns:1fr}.nav-bar{top:auto;position:relative}.header{position:relative}}"""

_ZH_JS = """const search=document.getElementById('search'),cards=document.querySelectorAll('.card'),pills=document.querySelectorAll('.nav-pill'),sections=document.querySelectorAll('.cat-section'),empty=document.getElementById('empty');let activeCat='all';function filter(){const q=search.value.trim().toLowerCase();let vis=0;cards.forEach(c=>{const nm=c.dataset.name,tx=c.textContent.toLowerCase();const co=activeCat==='all'||c.dataset.cat===activeCat;const qo=!q||nm.includes(q)||tx.includes(q);const sh=co&&qo;c.style.display=sh?'':'none';if(sh)vis++});sections.forEach(s=>{const vc=s.querySelectorAll('.card:not([style*="none"])').length;s.style.display=vc>0?'':'none'});document.querySelectorAll('.sub-group').forEach(g=>{const vc=g.querySelectorAll('.card:not([style*="none"])').length;g.style.display=vc>0?'':'none'});empty.style.display=vis===0?'block':'none'}search.addEventListener('input',filter);pills.forEach(p=>p.addEventListener('click',()=>{pills.forEach(x=>x.classList.remove('active'));if(p.dataset.cat===activeCat){activeCat='all'}else{p.classList.add('active');activeCat=p.dataset.cat}filter()}));"""


def _zh_card(skill):
    """Generate a single Chinese skill card HTML."""
    name = skill.get("name", "")
    desc = skill.get("description", "")
    if len(desc) > 300:
        desc = desc[:297] + "..."
    src = skill.get("source_type", "user")
    src_label, src_color = _ZH_SRC.get(src, (src, "#6b7280"))
    retired = skill.get("retired", False)
    pn = skill.get("parent_plugin", "")
    triggers = skill.get("triggers", [])
    trig_str = " / ".join(triggers[:6]) if triggers else ""
    scene = _infer_scene(name, desc)
    cls = "card retired" if retired else "card"
    nm_html = f'<span class="retired-name">{_html.escape(name)}</span>' if retired else f'<code class="skill-name">{_html.escape(name)}</code>'
    desc_html = _html.escape(desc) if not retired else f'<span style="text-decoration:line-through;color:#9ca3af">{_html.escape(desc)}</span>'
    rb = '<span class="badge" style="background:#6b7280">\u5df2\u9000\u5f79</span>' if retired else ""
    pt = f'<span class="plugin-tag">\u63d2\u4ef6: {_html.escape(pn)}</span>' if pn else ""
    return f'<div class="{cls}" data-name="{_html.escape(name.lower())}" data-cat=""><div class="card-head">{nm_html}<span class="badge" style="background:{src_color}">{src_label}</span>{pt}{rb}</div><div class="card-body"><div class="field"><span class="field-label">\u63cf\u8ff0</span><span class="field-val">{desc_html}</span></div><div class="field"><span class="field-label">\u9002\u7528\u573a\u666f</span><span class="field-val">{_html.escape(scene)}</span></div><div class="field"><span class="field-label">\u89e6\u53d1\u6761\u4ef6</span><span class="field-val trig">{_html.escape(trig_str)}</span></div></div></div>'


def to_html_zh(data):
    """Generate a Chinese, domain-categorized HTML report with deduplication."""
    cat = data["categories"]
    all_skills = []
    for key in ("system", "user_skills", "agents_skills"):
        all_skills.extend(cat.get(key, []))
    for p in cat.get("plugins", []):
        all_skills.extend(p.get("skills", []))
    all_skills = _dedupe_skills(all_skills)

    tree = _OD()
    for s in all_skills:
        domain, sub = _categorize_skill(s)
        tree.setdefault(domain, _OD()).setdefault(sub, []).append(s)

    total = len(all_skills)
    cat_counts = {d: sum(len(v) for v in subs.values()) for d, subs in tree.items()}

    src_totals = {}
    for s in all_skills:
        st = s.get("source_type", "user")
        src_totals[st] = src_totals.get(st, 0) + 1
    chips = "".join(
        f'<span class="chip" style="border-color:{_ZH_SRC[s][1]};color:{_ZH_SRC[s][1]}">{_ZH_SRC[s][0]} {src_totals[s]}</span>'
        for s in ["system", "user", "git", "agents", "plugin", "plugin-skill"] if s in src_totals
    )

    nav = "".join(
        f'<button class="nav-pill" data-cat="{_html.escape(d)}">{_html.escape(d)} <span class="count">{cat_counts[d]}</span></button>'
        for d in tree
    )

    secs = ""
    for domain, subs in tree.items():
        secs += f'<section class="cat-section"><h2 class="cat-title">{_html.escape(domain)} <span class="cat-count">{cat_counts[domain]}</span></h2>'
        for sub, skills in subs.items():
            secs += f'<div class="sub-group" data-cat="{_html.escape(domain)}"><h3 class="sub-title">{_html.escape(sub)}</h3><div class="card-grid">'
            for s in skills:
                card_html = _zh_card(s)
                card_html = card_html.replace('data-cat=""', f'data-cat="{_html.escape(domain)}"')
                secs += card_html
            secs += "</div></div>"
        secs += "</section>"

    return f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Codex \u6280\u80fd\u4e0e\u63d2\u4ef6\u6e05\u5355 \u00b7 \u6309\u5e94\u7528\u57df\u5206\u7c7b</title><style>{_ZH_CSS}</style></head><body><div class="header"><h1>Codex \u6280\u80fd\u4e0e\u63d2\u4ef6\u6e05\u5355</h1><div class="meta">\u626b\u63cf\u65f6\u95f4\uff1a{_html.escape(data["scan_time"])} \u00b7 \u5171 {total} \u9879 \u00b7 \u6309\u5e94\u7528\u57df\u5206\u7c7b</div><div class="chips">{chips}</div><input class="search-box" type="text" id="search" placeholder="\U0001F50D \u641c\u7d22\u6280\u80fd\u540d\u79f0\u3001\u63cf\u8ff0\u3001\u89e6\u53d1\u6761\u4ef6\u2026" autocomplete="off"></div><div class="nav-bar" id="navBar">{nav}</div><div class="main" id="main">{secs}</div><div class="empty" id="empty">\u672a\u627e\u5230\u5339\u914d\u7684\u6280\u80fd</div><script>{_ZH_JS}</script></body></html>'


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze installed Codex skills and plugins."
    )
    parser.add_argument(
        "--format", choices=["json", "markdown", "html", "all"], default="all",
        help="Output format (default: all = markdown + html)",
    )
    parser.add_argument(
        "--lang", choices=["en", "zh"], default="en",
        help="Report language: en (English, by source) or zh (Chinese, by application domain with dedup). Default: en",
    )
    parser.add_argument(
        "--codex-home", default=None,
        help="Custom .codex directory path (default: ~/.codex)",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output directory for markdown/html files (default: current directory)",
    )
    args = parser.parse_args()

    data = scan_all(codex_home=args.codex_home)

    out_dir = args.output or os.getcwd()
    os.makedirs(out_dir, exist_ok=True)

    use_zh = args.lang == "zh"

    if args.format == "json":
        print(to_json(data))
    elif args.format == "markdown":
        md = to_markdown(data)
        out_path = os.path.join(out_dir, "skill-inventory.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"Markdown report saved to: {out_path}")
    elif args.format == "html":
        html = to_html_zh(data) if use_zh else to_html(data)
        out_path = os.path.join(out_dir, "skill-inventory.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"HTML report saved to: {out_path}")
    elif args.format == "all":
        md = to_markdown(data)
        md_path = os.path.join(out_dir, "skill-inventory.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)

        html = to_html_zh(data) if use_zh else to_html(data)
        html_path = os.path.join(out_dir, "skill-inventory.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        json_path = os.path.join(out_dir, "skill-inventory.json")
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(to_json(data))

        print(f"Reports saved to {out_dir}:")
        print(f"  - skill-inventory.md")
        print(f"  - skill-inventory.html" + (" (zh)" if use_zh else ""))
        print(f"  - skill-inventory.json")

        if use_zh:
            zh_path = os.path.join(out_dir, "skill-inventory-zh.html")
            with open(zh_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  - skill-inventory-zh.html")


if __name__ == "__main__":
    main()
