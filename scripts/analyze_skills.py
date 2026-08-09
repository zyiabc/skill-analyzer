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

    if args.format == "json":
        print(to_json(data))
    elif args.format == "markdown":
        md = to_markdown(data)
        out_path = os.path.join(out_dir, "skill-inventory.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"Markdown report saved to: {out_path}")
    elif args.format == "html":
        html = to_html(data)
        out_path = os.path.join(out_dir, "skill-inventory.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"HTML report saved to: {out_path}")
    elif args.format == "all":
        md = to_markdown(data)
        md_path = os.path.join(out_dir, "skill-inventory.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)

        html = to_html(data)
        html_path = os.path.join(out_dir, "skill-inventory.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        json_path = os.path.join(out_dir, "skill-inventory.json")
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(to_json(data))

        print(f"Reports saved to {out_dir}:")
        print(f"  - skill-inventory.md")
        print(f"  - skill-inventory.html")
        print(f"  - skill-inventory.json")


if __name__ == "__main__":
    main()
