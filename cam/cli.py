#!/usr/bin/env python3
"""
CAM CLI — 一行命令管理你的 AI 知识库

安装:
    pip install cam

使用:
    cam init [path]          初始化新知识库
    cam ingest               处理 raw/ 中的原始资料
    cam query "问题"         基于知识库回答问题
    cam lint                 Wiki 健康检查
    cam stats                知识库统计
    cam status               运行状态面板
    cam collect <URL>        抓取网页入库
    cam start                启动自动化引擎（后台）
    cam version              显示版本号

示例:
    pip install cam
    cam init my-wiki
    cd my-wiki
    cp schema/PERSPECTIVE.example.md schema/PERSPECTIVE.md
    # 扔资料进 raw/，然后：
    cam ingest
    cam stats
"""

import os
import sys
import re
from datetime import datetime
from pathlib import Path

# ============================================================
# 颜色输出（跨平台兼容）
# ============================================================


class C:
    RED = "\033[91m" if os.name != "nt" else ""
    GREEN = "\033[92m" if os.name != "nt" else ""
    YELLOW = "\033[93m" if os.name != "nt" else ""
    BLUE = "\033[94m" if os.name != "nt" else ""
    CYAN = "\033[96m" if os.name != "nt" else ""
    BOLD = "\033[1m" if os.name != "nt" else ""
    DIM = "\033[2m" if os.name != "nt" else ""
    END = "\033[0m" if os.name != "nt" else ""


# ============================================================
# 工具函数
# ============================================================

VERSION = "2.0.0"

WIKI_DIR = "wiki"
RAW_DIR = "raw"
SCHEMA_DIR = Path("schema")
OUTPUTS_DIR = "outputs"

CONCEPT_DIR = os.path.join(WIKI_DIR, "concept")
ENTITY_DIR = os.path.join(WIKI_DIR, "entity")
SYNTHESIS_DIR = os.path.join(WIKI_DIR, "synthesis")

INDEX_FILE = os.path.join(WIKI_DIR, "index.md")
CHANGELOG_FILE = os.path.join(WIKI_DIR, "changelog.md")
CLAUDE_FILE = os.path.join(SCHEMA_DIR, "CLAUDE.md")


def find_wiki_root(start=None):
    """向上查找 CAM 项目根目录（通过 CLAUDE.md 定位）"""
    current = Path(start or os.getcwd())
    while current != current.parent:
        if (current / CLAUDE_FILE).exists():
            return str(current)
        current = current.parent
    return None


def ensure_wiki_root():
    """确保在 CAM 项目目录内，否则退出"""
    root = find_wiki_root()
    if not root:
        print(f"{C.RED}❌ 错误: 未找到 CAM 项目{C.END}")
        print("\n请先初始化一个项目:")
        print(f"  {C.CYAN}cam init <路径>{C.END}")
        sys.exit(1)
    return root


def get_all_md_files(directory):
    """获取目录下所有 .md 文件"""
    if not os.path.exists(directory):
        return []
    return [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(".md") and not f.startswith(".")]


def extract_frontmatter(content):
    """提取 Markdown YAML frontmatter"""
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if match:
        fm_text = match.group(1)
        frontmatter = {}
        for line in fm_text.split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip().strip("\"'")
                if value.startswith("[") and value.endswith("]"):
                    value = [v.strip().strip("\"'") for v in value[1:-1].split(",")]
                frontmatter[key] = value
        return frontmatter
    return {}


def extract_links(content):
    """提取所有 [[双链]] 链接"""
    return re.findall(r"\[\[(?!http)(.+?)\]\]", content)


# ============================================================
# 命令实现
# ============================================================


def cmd_init(path="."):
    """
    初始化一个新的 CAM 项目。

    创建完整的目录结构、复制规则文件模板、生成 .gitkeep。
    这就是「开箱即用」的核心入口。
    """
    target = Path(path).resolve()

    # 检查目标是否已有内容
    if target.exists() and any(target.iterdir()):
        print(f"{C.YELLOW}⚠️  目录 {target} 已存在且有内容{C.END}")
        print("将在现有目录中创建缺失的文件/文件夹...\n")

    # 完整的目录结构
    dirs = {
        RAW_DIR: "# Raw 资料目录\n\n将原始资料（文章、论文、笔记等）放入此目录。\n支持格式: .md, .txt, .pdf（需转文本）\n\n**规则**: 此目录下的文件 AI 只读不写。",
        CONCEPT_DIR: None,
        ENTITY_DIR: None,
        SYNTHESIS_DIR: None,
        OUTPUTS_DIR: None,
        SCHEMA_DIR / "templates": None,
        ".cam_core": None,
        Path("auto") / "logs": None,
        Path("auto") / "state": None,
        Path("examples") / "raw-sample": None,
    }

    print(f"{C.BOLD}{C.BLUE}🧠 CAM v{VERSION}{C.END}")
    print(f"{C.BOLD}   AI 驱动的复利记忆系统{C.END}\n")
    print("🚀 正式始初始化...")
    print(f"   📍 目标目录: {target}\n")

    for rel_dir, placeholder_content in dirs.items():
        d = target / rel_dir
        d.mkdir(parents=True, exist_ok=True)
        print(f"  {C.GREEN}✓{C.END} {rel_dir}/")

    # 写入 .gitkeep 到空目录
    gitkeep_dirs = [
        RAW_DIR,
        CONCEPT_DIR,
        ENTITY_DIR,
        SYNTHESIS_DIR,
        OUTPUTS_DIR,
        ".cam_core",
        "auto/logs",
        "auto/state",
        "examples/raw-sample",
    ]
    for gd in gitkeep_dirs:
        gp = target / gd / ".gitkeep"
        if not gp.exists():
            gp.write_text("", encoding="utf-8")

    # 写入 raw/ 说明文件
    raw_readme = target / RAW_DIR / "README.md"
    if not raw_readme.exists():
        raw_readme.write_text(dirs[RAW_DIR], encoding="utf-8")

    # 写入 PERSPECTIVE 模板（如果不存在）
    perspective_example = target / SCHEMA_DIR / "PERSPECTIVE.example.md"
    perspective_target = target / SCHEMA_DIR / "PERSPECTIVE.md"
    if not perspective_example.exists() and not perspective_target.exists():
        perspective_content = """# 你的视角偏好 (PERSPECTIVE)

> 这是可选配置。编辑此文件可以让 AI 更好地理解你的背景和偏好。

## 基本信息

- **名字**: （你的名字或昵称）
- **角色**: （开发者 / 研究者 / 学生 / 创业者 / ...）
- **主要领域**: （你关注的技术领域）
- **经验水平**: （初学者 / 中级 / 高级）

## 偏好设置

### 写作风格
- （你喜欢的文档风格：简洁详细 / 学术严谨 / 轻松活泼）

### 语言
- 主要语言：（中文 / English / ...）

### 技术栈
- 你常用的技术栈和工具

## 知识关注点

-你最想积累哪方面的知识？（可以随时修改）
"""
        perspective_example.write_text(perspective_content, encoding="utf-8")
        print(f"  {C.GREEN}✓{C.END} schema/PERSPECTIVE.example.md (模板)")

    # 写入 CLAUDE.md 规则文件（如果不存在）
    claude_path = target / CLAUDE_FILE
    if not claude_path.exists():
        claude_content = """# CAM 知识组织规则 (CLAUDE.md)

> 这个文件告诉 AI 如何组织和维护你的知识库。

## 📚 知识库结构

```
wiki/
├── entity/      # 实体页：人、项目、工具、具体事物
├── concept/     # 概念页：技术、方法、抽象概念
└── synthesis/   # 综合页：决策、偏好、经验教训
```

## 🏷️ 知识分类规则

### entity/ — 实体页
- **谁**: 人名、团队名、角色
- **什么**: 项目名、工具名、服务名
- **特征**: 具体的、可命名的对象
- **示例**: `PostgreSQL`, `CAM`, `张三`

### concept/ — 概念页
- **技术**: 框架、库、语言、架构模式
- **方法**: TDD、CI/CD、Git 工作流
- **约定**: 项目规范、编码风格、工作惯例
- **示例**: `异步编程模式`, `分层架构`

### synthesis/ — 综合页
- **决策**: 技术选型、架构决定（附理由）
- **偏好**: 用户习惯、个人偏好
- **问题/解决**: 遇到的 bug 和修复方案
- **经验**: 踩过的坑、学到的教训
- **示例**: `为什么选择 FastAPI`, `PostgreSQL 连接池问题`

## ✍️ 页面格式

每个页面应该是这样的 Markdown：

```markdown
# 标题

> 一句话总结

## 详情

具体内容...

## 相关

- [[相关页面1]]
- [[相关页面2]]

*由 CAM 自动生成*
```

## 📥 工作流程

1. **Ingest**: 从 `raw/` 读取原始资料 → 编译到 `wiki/`
2. **Query**: 从 `wiki/` 检索知识 → 注入对话上下文
3. **Lint**: 定期检查 wiki 一致性 → 修复断链和重复

## ⚠️ 质量规则

- 每条知识应该原子化（一个事实一页）
- 避免重复：检查是否已有类似页面
- 保持简洁：不要复制大段原文
- 标记来源：知识是从哪里来的
- 跨项目区分：如果涉及多个项目，用标签标注

## 🔄 维护

- 发现过时内容时更新
- 合并重复页面
- 修复损坏的双链引用
- 定期整理索引
"""
        claude_path.write_text(claude_content, encoding="utf-8")
        print(f"  {C.GREEN}✓{C.END} schema/CLAUDE.md (规则文件)")

    # 写入 wiki/index.md 如果不存在
    index_path = target / INDEX_FILE
    if not index_path.exists():
        index_content = """# CAM — 全局索引

> 自动维护，**不要手动编辑**

## 📊 概览

| 类别 | 数量 |
|------|------|
| 概念页 | 0 |
| 实体页 | 0 |
| 综合页 | 0 |

## 🔗 最近更新

_(暂无)_

---

*由 CAM Memory Core 自动生成*
"""
        index_path.write_text(index_content, encoding="utf-8")
        print(f"  {C.GREEN}✓{C.END} wiki/index.md")

    # 写入 wiki/changelog.md 如果不存在
    changelog_path = target / CHANGELOG_FILE
    if not changelog_path.exists():
        changelog_content = """# Change Log

> 每次 INGEST 操作自动记录变更

---

## 待处理

*(尚未执行任何 INGEST)*
"""
        changelog_path.write_text(changelog_content, encoding="utf-8")
        print(f"  {C.GREEN}✓{C.END} wiki/changelog.md")

    print(f"\n{C.BOLD}{C.GREEN}✅ 初始化完成！{C.END}")
    print()
    print(f"下一步操作 ({C.DIM}3 步开始使用{C.END}):")
    print(f"  1️⃣  {C.CYAN}cd {target.name}{C.END}")
    print(f"  2️⃣  编辑 {C.CYAN}schema/PERSPECTIVE.md{C.END} 设置你的身份偏好:")
    print(f"      {C.DIM}cp schema/PERSPECTIVE.example.md schema/PERSPECTIVE.md{C.END}")
    print()
    print("然后就可以用了:")
    print(f"  📥 把资料扔进 {C.CYAN}raw/{C.END}")
    print(f'  🤖 对 AI 说 {C.CYAN}"INGEST"{C.END} 或运行 {C.CYAN}cam ingest{C.END}')
    print(f"  📊 查看: {C.CYAN}cam stats{C.END} / {C.CYAN}cam lint{C.END}")
    print()


def cmd_lint(wiki_root=None):
    """Wiki 健康检查"""
    root = wiki_root or ensure_wiki_root()

    print(f"{C.BOLD}🔍 CAM LINT 检查{C.END}")
    print(f"   项目: {root}\n")

    issues = {"severe": [], "warning": [], "info": [], "hint": []}

    concept_files = get_all_md_files(os.path.join(root, CONCEPT_DIR))
    entity_files = get_all_md_files(os.path.join(root, ENTITY_DIR))
    synthesis_files = get_all_md_files(os.path.join(root, SYNTHESIS_DIR))
    all_files = concept_files + entity_files + synthesis_files
    all_pages = {}

    total_pages = len(all_files)

    if total_pages == 0:
        print("  ℹ️  Wiki 为空。\n  💡 将资料放入 raw/ 后执行 INGEST。")
        return

    for fp in all_files:
        name = Path(fp).stem
        all_pages[name.lower()] = fp

    link_map = {}
    backlink_map = {name: [] for name in all_pages}

    for fp in all_files:
        try:
            content = open(fp, encoding="utf-8").read()
            links = extract_links(content)
            page_name = Path(fp).stem.lower()
            link_map[page_name] = links
            for link in links:
                link_lower = link.lower()
                if link_lower in all_pages:
                    backlink_map[link_lower].append(page_name)
        except Exception as e:
            issues["warning"].append({"type": "读取失败", "file": fp, "detail": str(e)})

    # 孤立页面检测
    for name, fp in all_pages.items():
        out_links = link_map.get(name, [])
        in_links = backlink_map.get(name, [])
        has_out = any(l.lower() in all_pages for l in out_links)
        has_in = len(in_links) > 0
        if not has_out and not has_in and total_pages > 1:
            issues["warning"].append(
                {
                    "type": "孤立页面",
                    "file": fp,
                    "detail": f"(出链:{len(out_links)}, 入链:{len(in_links)})",
                }
            )

    # 待建链接
    unresolved = set()
    for name, links in link_map.items():
        for link in links:
            if link.lower() not in all_pages:
                unresolved.add(link)

    for link in sorted(unresolved):
        ref_count = sum(1 for ls in link_map.values() for l in ls if l.lower() == link.lower())
        if ref_count >= 2:
            issues["hint"].append(
                {
                    "type": "待建链接",
                    "link": link,
                    "detail": f"被 {ref_count} 个页面引用",
                }
            )
        else:
            issues["info"].append({"type": "未解析链接", "link": link})

    # Frontmatter 检查
    required_fields = ["title", "type", "status"]
    for fp in all_files:
        try:
            content = open(fp, encoding="utf-8").read()
            fm = extract_frontmatter(content)
            missing = [f for f in required_fields if f not in fm]
            if missing:
                issues["info"].append(
                    {
                        "type": "Frontmatter 不完整",
                        "file": fp,
                        "detail": f"缺少: {', '.join(missing)}",
                    }
                )
        except Exception:
            pass

    # ---- 输出报告 ----
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"  ⏰ 时间: {now}")
    print(
        f"  📄 页面: {total_pages} ({len(concept_files)} 概念 + {len(entity_files)} 实体 + {len(synthesis_files)} 综合)\n"
    )

    severity_order = [
        ("severe", "🔴", "严重"),
        ("warning", "🟠", "中等"),
        ("info", "🔵", "低"),
        ("hint", "🟢", "提示"),
    ]

    total_issues = sum(len(issues[k]) for k in issues)
    print(f"{C.BOLD}  问题汇总{C.END}  {'─' * 35}")

    for key, icon, label in severity_order:
        count = len(issues[key])
        icon_display = icon if count > 0 else "✅"
        print(f"  {icon_display} {label}: {count}")

    print(f"\n  总计: {total_issues} 个问题\n")

    if total_issues > 0:
        for key, icon, label in severity_order:
            if not issues[key]:
                continue
            print(f"  {icon} {label} ({len(issues[key])})")
            print(f"  {'─' * 42}")
            for i, issue in enumerate(issues[key], 1):
                if "file" in issue:
                    print(f"  {i}. [{issue['type']}] {os.path.relpath(issue['file'], root)}")
                elif "link" in issue:
                    print(f"  {i}. [{issue['type']}] [[{issue['link']}]]")
                detail = issue.get("detail", "")
                if detail:
                    print(f"     → {detail}")

    # 健康评分
    max_score = total_pages * 10
    deduction = total_issues * 2
    score = max(0, min(100, max_score - deduction)) if max_score > 0 else 100
    color = C.GREEN if score >= 80 else (C.YELLOW if score >= 60 else C.RED)

    print(f"\n{'─' * 45}")
    print(f"  📊 健康评分: {color}{score}/100{C.END}")

    if score >= 80:
        print("  ✅ 知识库状态良好！")
    elif score >= 60:
        print("  ⚠️  有一些小问题需要处理。")
    else:
        print("  ❌ 存在较多问题，建议执行维护。")


def cmd_stats(wiki_root=None):
    """知识库统计信息"""
    root = wiki_root or ensure_wiki_root()

    concept_files = get_all_md_files(os.path.join(root, CONCEPT_DIR))
    entity_files = get_all_md_files(os.path.join(root, ENTITY_DIR))
    synthesis_files = get_all_md_files(os.path.join(root, SYNTHESIS_DIR))
    raw_files = get_all_md_files(os.path.join(root, RAW_DIR))

    all_wiki = concept_files + entity_files + synthesis_files
    total_links = 0
    total_words = 0
    tags_set = set()

    for fp in all_wiki:
        try:
            content = open(fp, encoding="utf-8").read()
            total_links += len(extract_links(content))
            total_words += len(content.split())
            fm = extract_frontmatter(content)
            tags = fm.get("tags", [])
            if isinstance(tags, list):
                tags_set.update(tags)
        except Exception:
            pass

    print(f"{C.BOLD}📊 CAM 统计{C.END}")
    print(f"   项目: {root}\n")

    print("  📁 Wiki 页面:")
    print(f"     概念 (concept/):    {len(concept_files):>4}")
    print(f"     实体 (entity/):     {len(entity_files):>4}")
    print(f"     综合 (synthesis/):  {len(synthesis_files):>4}")
    print(f"     {'─' * 22}")
    print(f"     合计:               {len(all_wiki):>4}")
    print(f"\n  📥 Raw 资料: {len(raw_files)} 个文件")

    if all_wiki:
        print("\n  🔗 关联:")
        print(f"     双链总数:       {total_links}")
        print(f"     平均每页链接:   {total_links / len(all_wiki):.1f}")
        print(f"     总字数:         ~{total_words:,}")
        print(f"     标签种类:       {len(tags_set)}")

        if tags_set:
            tag_str = "  ".join(f"[{t}]" for t in sorted(tags_set)[:15])
            print("\n  🏷️ 标签云:")
            print(f"     {tag_str}")
            if len(tags_set) > 15:
                print(f"     ... 等 {len(tags_set)} 个标签")

    print("\n  🕒 最近更新:")
    if all_wiki:
        recent = sorted(all_wiki, key=lambda f: os.path.getmtime(f), reverse=True)[:5]
        for fp in recent:
            mtime = datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M")
            rel = os.path.relpath(fp, root)
            print(f"     {mtime}  {rel}")
    else:
        print("     (暂无内容)")


def cmd_status(wiki_root=None):
    """运行状态总览"""
    root = wiki_root or find_wiki_root()

    print(f"{C.BOLD}⚡ CAM Status{C.END}\n")
    print(f"  版本:    v{VERSION}")
    print(f"  Python:  {sys.version.split()[0]}")
    print(f"  项目:   {root or '(未在项目内)'}")

    if root:
        # 各模块状态
        checks = [
            ("schema/CLAUDE.md", "规则定义"),
            ("wiki/index.md", "Wiki 索引"),
            ("raw/", "资料目录"),
            (".cam_core/", "Memory Core"),
            ("auto/config.json", "自动引擎"),
        ]
        print("\n  模块状态:")
        for path_item, label in checks:
            full = os.path.join(root, path_item)
            exists = os.path.exists(full)
            icon = "✅" if exists else "⬜"
            status = "就绪" if exists else "未初始化"
            print(f"    {icon} {label:<12} {status}")


def cmd_ingest(wiki_root=None):
    """提示如何执行 INGEST"""
    root = wiki_root or ensure_wiki_root()
    raw_dir = os.path.join(root, RAW_DIR)

    if not os.path.exists(raw_dir):
        print(f"{C.YELLOW}raw/ 目录不存在{C.END}")
        return

    files = [f for f in os.listdir(raw_dir) if not f.startswith(".") and f != ".gitkeep"]

    print(f"{C.BOLD}📥 INGEST — 处理原始资料{C.END}\n")

    if not files:
        print("  📭 raw/ 为空")
        print(f"\n  把资料 (.md/.txt) 放入 {C.CYAN}raw/{C.END} 后重新运行此命令。")
        return

    print(f"  发现 {len(files)} 个待处理文件:")
    for f in sorted(files)[:20]:
        fp = os.path.join(raw_dir, f)
        size = os.path.getsize(fp)
        sz = f"{size / 1024:.1f}KB" if size > 1024 else f"{size}B"
        ext = os.path.splitext(f)[1].lower()
        icon = {"md": "📝", "txt": "📄", "pdf": "📕", "png": "🖼️", "jpg": "🖼️"}.get(ext, "📎")
        print(f"    {icon} {f:<40} {sz:>8}")

    if len(files) > 20:
        print(f"    ... 还有 {len(files) - 20} 个文件")

    print(f"\n  {C.BOLD}{C.YELLOW}→ 请对 AI Agent 发出以下指令:{C.END}")
    print(f'  {C.DIM}"请读取 raw/ 目录中的所有新文件，按照 schema/CLAUDE.md 的规则')
    print("   提取核心概念和实体，创建/更新 Wiki 页面，建立 [[双链]] 关联，")
    print(f'   更新 wiki/index.md 和 wiki/changelog.md。"{C.END}')


def cmd_query(question, wiki_root=None):
    """基于知识库查询（打印提示）"""
    root = wiki_root or ensure_wiki_root()

    if not question:
        print(f'用法: {C.CYAN}cam query "你的问题"{C.END}')
        print("\n示例:")
        print('  cam query "什么是 RAG？"')
        print('  cam query "我们选了什么数据库？"')
        return

    print(f"{C.BOLD}❓ QUERY — 知识库查询{C.END}\n")
    print(f'  问题: {C.CYAN}"{question}"{C.END}')
    print(f"\n  {C.YELLOW}→ 请对 AI Agent 发出:{C.END}")
    print(f"  {C.DIM}\"基于 wiki/ 中的内容回答: '{question}'\"{C.END}")


def cmd_version():
    """显示版本信息"""
    print(f"CAM v{VERSION}")
    print("AI-driven compound interest memory system")
    print(f"\n安装位置: {os.path.dirname(os.path.dirname(__file__))}")


def cmd_help():
    """显示帮助信息"""
    print(f"""{C.BOLD}{C.BLUE}🧠 CAM v{VERSION}{C.END}
{C.BOLD}   AI 驱动的复利记忆系统{C.END}

{C.BOLD}用法:{C.END}  {C.CYAN}cw <命令> [参数]{C.END}

{C.BOLD}快速开始:{C.END}
  cam init [路径]         初始化新的知识库项目
  cam ingest              处理 raw/ 中的资料
  cam query \"问题\"        基于知识库提问

{C.BOLD}管理与诊断:{C.END}
  cam lint                Wiki 健康 LINT 检查
  cam stats               知识库统计信息
  cam status              运行状态总览
  cam check-raw           查看 raw/ 未处理文件

{C.BOLD}高级功能:{C.END}
  cam collect <URL>       抓取网页入库
  cam start               启动自动化后台引擎
  cam version             显示版本信息

{C.BOLD}示例:{C.END}
  $ pip install cam
  $ cam init my-knowledge-base
  $ cd my-knowledge-base
  $ cam ingest
  $ cam stats

{C.BOLD}更多信息:{C.END}
  GitHub: https://github.com/canyonqian/cam
  Docs:   https://github.com/canyonqian/cam#readme
""")


# ============================================================
# 主入口
# ============================================================


def main():
    """CLI 主入口 — 被 pyproject.toml 的 [project.scripts] 引用"""
    args = sys.argv[1:]

    if not args:
        cmd_help()
        return

    command = args[0].lower()
    rest = args[1:]

    dispatch = {
        "init": lambda: cmd_init(
            (rest[1] if len(rest) > 1 and rest[0] in ("--dir", "-d") else rest[0]) if rest else "."
        ),
        "lint": lambda: cmd_lint(rest[0] if rest else None),
        "stats": lambda: cmd_stats(rest[0] if rest else None),
        "status": lambda: cmd_status(rest[0] if rest else None),
        "ingest": lambda: cmd_ingest(None),
        "query": lambda: cmd_query(" ".join(rest) if rest else ""),
        "check-raw": lambda: cmd_check_raw(rest[0] if rest else None),
        "collect": lambda: cmd_collect(rest[0] if rest else ""),
        "start": lambda: cmd_start(),
        "daemon": lambda: cmd_daemon(),  # v2 新增: 守护进程管理
        "--help": cmd_help,
        "-h": cmd_help,
        "version": cmd_version,
        "-v": cmd_version,
        "--version": cmd_version,
    }

    handler = dispatch.get(command)
    if handler:
        handler()
    elif command == "help":
        subcmd = rest[0] if rest else None
        if subcmd and subcmd in dispatch:
            # 可以扩展为子命令帮助
            cmd_help()
        else:
            cmd_help()
    else:
        print(f"{C.RED}未知命令: {command}{C.END}")
        print(f"运行 {C.CYAN}cam --help{C.END} 查看所有可用命令")
        sys.exit(1)


# 为了兼容旧脚本中的 check-raw
def cmd_check_raw(wiki_root=None):
    """列出 raw/ 中未处理的文件"""
    root = wiki_root or ensure_wiki_root()
    raw_dir = os.path.join(root, RAW_DIR)

    if not os.path.exists(raw_dir):
        print("ℹ️  raw/ 目录不存在")
        return

    raw_files = sorted(f for f in os.listdir(raw_dir) if not f.startswith(".") and f != ".gitkeep")

    print(f"{C.BOLD}📥 Raw 资料清单{C.END}\n")

    if not raw_files:
        print("  📭 raw/ 目录为空\n  💡 将资料放入后执行 cam ingest")
        return

    total_size = 0
    for i, fname in enumerate(raw_files, 1):
        fpath = os.path.join(raw_dir, fname)
        size = os.path.getsize(fpath)
        total_size += size
        size_str = f"{size / 1024:.1f}KB" if size > 1024 else f"{size}B"
        ext = os.path.splitext(fname)[1].lower()
        icon = {"md": "📝", "txt": "📄", "pdf": "📕", "png": "🖼️", "jpg": "🖼️"}.get(ext, "📎")
        print(f"  {i}. {icon} {fname:<40} {size_str:>8}")

    print(f"\n  共 {len(raw_files)} 个文件, 总大小: {total_size / 1024:.1f} KB")


def cmd_collect(url):
    """抓取 URL 并存入 raw/"""
    if not url:
        print(f"用法: {C.CYAN}cam collect <URL>{C.END}")
        print("\n示例: cam collect https://example.com/article")
        return

    print(f"{C.BOLD}🌐 COLLECT — 抓取网页{C.END}")
    print(f"  URL: {url}")
    print(f"\n  {C.YELLOW}需要安装额外依赖:{C.END}")
    print(f"  {C.DIM}pip install 'cam[all]'{C.END}")


def cmd_start():
    """启动自动化引擎"""
    print(f"{C.BOLD}⚡ START — 启动自动化引擎{C.END}")
    print(f"\n  {C.YELLOW}需要安装自动化依赖:{C.END}")
    print(f"  {C.DIM}pip install 'cam[auto]'${C.END}")
    print("\n  或者直接运行:")
    print(f"  {C.DIM}python auto/agent.py start{C.END}")


# ── Daemon 子命令 (v2 新增) ────────────────────────────────


def cmd_daemon():
    """Daemon 命令路由 — cam daemon [start|stop|status]"""
    from . import cli_daemon
    import sys

    sub_args = []
    # Find "daemon" in args and get what comes after it
    found = False
    for a in sys.argv[1:]:
        if not found:
            if a.lower() == "daemon":
                found = True
            continue
        sub_args.append(a)

    if not sub_args or sub_args[0].startswith("-"):
        cmd_daemon_help()
        return

    sub_cmd = sub_args[0].lower()
    rest_args = sub_args[1:]

    dispatch = {
        "start": lambda: cli_daemon.cmd_daemon_start(rest_args),
        "stop": lambda: cli_daemon.cmd_daemon_stop(),
        "restart": lambda: cli_daemon.cmd_daemon_restart(rest_args),
        "status": lambda: cli_daemon.cmd_daemon_status(),
        "ping": lambda: cli_daemon.cmd_daemon_ping(),
        "--help": cmd_daemon_help,
        "-h": cmd_daemon_help,
    }

    handler = dispatch.get(sub_cmd)
    if handler:
        handler()
    else:
        print(f"{C.RED}未知 daemon 命令: {sub_cmd}{C.END}")
        print("可用: start | stop | restart | status | ping")
        sys.exit(1)


def cmd_daemon_help():
    print(f"""{C.BOLD}{C.BLUE}🔧 CAM Daemon v2.0.0{C.END}
{C.BOLD}   全自动通用 Agent 记忆守护进程{C.END}

{C.BOLD}用法:{C.END}  {C.CYAN}cam daemon <命令> [参数]{C.END}

{C.BOLD}核心命令:{C.END}
  cam daemon start [--wiki ./wiki] [--port 9877]
                       启动守护进程（后台运行）
  cam daemon stop          停止守护进程
  cam daemon restart       重启守护进程
  cam daemon status        查看运行状态
  cam daemon ping          快速检查是否在线

{C.BOLD}参数:{C.END}
  --wiki <路径>           Wiki 目录（默认: ./wiki）
  --port <端口>           API 端口（默认: 9877）
  --host <地址>           绑定地址（默认: 127.0.0.1）
  --llm-provider <名称>   LLM 提供商 openai|anthropic|ollama
  --llm-model <模型名>    提取用模型（默认: gpt-4o-mini）
  --config <文件>         配置文件路径

{C.BOLD}Agent 集成示例:{C.END}
  # Python Agent (3行)
  >>> from cam_daemon.client import CamClient
  >>> client = CamClient()
  >>> await client.remember(user_msg, ai_response, agent_id="my-bot")

  # Shell / curl (1行)
  $ curl -X POST http://localhost:9877/hook -d '{{"user_message":"...", "ai_response":"..."}}'

  # Hermes / OpenClaw hook (3行)
  requests.post("http://localhost:9877/hook", json={...})

{C.BOLD}API 端点:{C.END}
  POST /hook              发送对话 → 自动提取+写入
  POST /ingest            手动摄入内容
  GET  /query?q=...       查询知识库
  GET  /stats             统计信息
  GET  /health            健康检查
""")


if __name__ == "__main__":
    main()
