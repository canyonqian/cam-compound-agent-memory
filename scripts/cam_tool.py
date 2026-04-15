#!/usr/bin/env python3
"""
CAM - 辅助工具集

功能：
  1. init      - 初始化新的 CAM 项目
  2. lint      - 生成 Wiki 健康检查报告（供 AI 审计使用）
  3. stats     - 显示知识库统计信息
  4. check-raw - 检查 raw/ 中未处理的文件

使用方法:
  python cam_tool.py <命令> [参数]

注意：此脚本提供辅助功能，核心的 Wiki 编译工作由 AI Agent 完成。
"""

import os
import sys
import re
import json
from datetime import datetime
from pathlib import Path


# ============================================================
# 配置
# ============================================================

WIKI_DIR = "wiki"
RAW_DIR = "raw"
SCHEMA_DIR = "schema"
OUTPUTS_DIR = "outputs"

CONCEPT_DIR = os.path.join(WIKI_DIR, "concept")
ENTITY_DIR = os.path.join(WIKI_DIR, "entity")
SYNTHESIS_DIR = os.path.join(WIKI_DIR, "synthesis")

INDEX_FILE = os.path.join(WIKI_DIR, "index.md")
CHANGELOG_FILE = os.path.join(WIKI_DIR, "changelog.md")
CLAUDE_FILE = os.path.join(SCHEMA_DIR, "CLAUDE.md")

# 颜色输出（跨平台兼容）
class Colors:
    RED = "\033[91m" if os.name != "nt" else ""
    GREEN = "\033[92m" if os.name != "nt" else ""
    YELLOW = "\033[93m" if os.name != "nt" else ""
    BLUE = "\033[94m" if os.name != "nt" else ""
    CYAN = "\033[96m" if os.name != "nt" else ""
    BOLD = "\033[1m" if os.name != "nt" else ""
    END = "\033[0m" if os.name != "nt" else ""


# ============================================================
# 工具函数
# ============================================================

def find_wiki_root():
    """查找 CAM 项目根目录"""
    current = Path.cwd()
    while current != current.parent:
        if (current / CLAUDE_FILE).exists():
            return str(current)
        current = current.parent
    return None


def get_all_md_files(directory):
    """获取目录下所有 .md 文件"""
    if not os.path.exists(directory):
        return []
    return [
        os.path.join(directory, f) 
        for f in os.listdir(directory) 
        if f.endswith(".md") and not f.startswith(".")
    ]


def extract_frontmatter(content):
    """提取 Markdown 文件的 YAML frontmatter"""
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if match:
        fm_text = match.group(1)
        frontmatter = {}
        for line in fm_text.split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip().strip("\"'")
                # 处理列表值
                if value.startswith("[") and value.endswith("]"):
                    value = [v.strip().strip("\"'") for v in value[1:-1].split(",")]
                frontmatter[key] = value
        return frontmatter
    return {}


def extract_links(content):
    """提取所有 [[双链]] 链接"""
    return re.findall(r"\[\[(.+?)\]\]", content)


def extract_internal_links(content):
    """提取内部 wiki 链接（排除 URL）"""
    return re.findall(r"\[\[(?!http)(.+?)\]\]", content)


# ============================================================
# 命令：init - 初始化项目
# ============================================================

def cmd_init(path="."):
    """初始化一个新的 CAM 项目"""
    target = Path(path)

    dirs = [
        target / RAW_DIR,
        target / CONCEPT_DIR,
        target / ENTITY_DIR,
        target / SYNTHESIS_DIR,
        target / SCHEMA_DIR / "templates",
        target / OUTPUTS_DIR,
        target / "scripts",
        target / "examples" / "raw-sample",
    ]

    print(f"{Colors.BOLD}🚀 初始化 CAM 项目...{Colors.END}")
    print(f"   目标目录: {target.absolute()}\n")

    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        print(f"  {Colors.GREEN}✓{Colors.END} 创建: {d.relative_to(target)}")

    # 写入占位文件
    placeholder_files = {
        RAW_DIR / ".gitkeep": "# Raw 资料目录\n\n将原始资料（文章、论文、笔记等）放入此目录。\n支持格式: .md, .txt, .pdf（需转文本）, 图片\n\n**规则**: 此目录下的文件 AI 只读不写。",
        OUTPUTS_DIR / ".gitkeep": "# Outputs 目录\n\n存放基于知识库生成的问答结果和分析报告。",
    }

    for rel_path, content in placeholder_files.items():
        full_path = target / rel_path
        if not full_path.exists():
            full_path.write_text(content, encoding="utf-8")
            print(f"  {Colors.GREEN}✓{Colors.END} 创建: {rel_path}")

    print(f"\n{Colors.BOLD}{Colors.GREEN}✅ 初始化完成！{Colors.END}")
    print(f"\n下一步操作:")
    print(f"  1. 编辑 {Colors.CYAN}schema/CLAUDE.md{Colors.END} 定义你的知识库规则")
    print(f"  2. （可选）编辑 {Colors.CYAN}schema/PERSPECTIVE.example.md{Colors.END} 并重命名为 PERSPECTIVE.md")
    print(f"  3. 将资料放入 {Colors.CYAN}raw/{Colors.END} 目录")
    print(f"  4. 对 AI 发出 INGEST 指令开始编译 Wiki\n")


# ============================================================
# 命令：lint - 健康检查
# ============================================================

def cmd_lint(wiki_root=None):
    """执行 Wiki 健康 LINT 检查"""
    
    root = wiki_root or find_wiki_root()
    if not root:
        print(f"{Colors.RED}❌ 错误: 未找到 CAM 项目根目录{Colors.END}")
        print("请在 CAM 项目目录内运行此命令，或指定路径: python cam_tool.py lint <路径>")
        sys.exit(1)

    print(f"{Colors.BOLD}🔍 CAM LINT 检查{Colors.END}")
    print(f"   项目路径: {root}\n")

    issues = {
        "severe": [],      # 🔴 内容矛盾
        "warning": [],     # 🟠 孤立页面 / 缺失引用
        "info": [],        # 🔵 过时标记 / 待建链接
        "hint": [],        # 🟢 改进建议
    }

    # 收集所有 Wiki 页面
    concept_files = get_all_md_files(os.path.join(root, CONCEPT_DIR))
    entity_files = get_all_md_files(os.path.join(root, ENTITY_DIR))
    synthesis_files = get_all_md_files(os.path.join(root, SYNTHESIS_DIR))
    
    all_files = concept_files + entity_files + synthesis_files
    all_pages = {}  # name -> filepath
    
    total_pages = len(all_files)
    
    if total_pages == 0:
        print(f"  ℹ️  Wiki 目录为空，无需检查。\n")
        print(f"  💡 提示: 将资料放入 raw/ 后对 AI 发出 INGEST 指令。")
        return

    # 构建页面索引
    for fp in all_files:
        name = Path(fp).stem
        all_pages[name.lower()] = fp

    # 统计链接关系
    link_map = {}  # page -> [linked_pages]
    backlink_map = {name: [] for name in all_pages}
    
    for fp in all_files:
        try:
            content = open(fp, encoding="utf-8").read()
            links = extract_internal_links(content)
            page_name = Path(fp).stem.lower()
            link_map[page_name] = links
            
            for link in links:
                link_lower = link.lower()
                if link_lower in all_pages:
                    backlink_map[link_lower].append(page_name)
        except Exception as e:
            issues["warning"].append({
                "type": "读取失败",
                "file": fp,
                "detail": str(e)
            })

    # ---- 检查 1: 孤立页面 ----
    for name, fp in all_pages.items():
        out_links = link_map.get(name, [])
        in_links = backlink_map.get(name, [])
        
        has_out_link = any(l.lower() in all_pages for l in out_links)
        has_in_link = len(in_links) > 0
        
        if not has_out_link and not has_in_link and total_pages > 1:
            issues["warning"].append({
                "type": "孤立页面",
                "file": fp,
                "detail": f"该页面没有任何有效链接（出链:{len(out_links)}, 入链:{len(in_links)}）"
            })

    # ---- 检查 2: 待建链接 ----
    unresolved_links = set()
    for name, links in link_map.items():
        for link in links:
            link_lower = link.lower()
            if link_lower not in all_pages:
                unresolved_links.add(link)
    
    if unresolved_links:
        for link in sorted(unresolved_links):
            ref_count = sum(
                1 for links in link_map.values() 
                for l in links if l.lower() == link.lower()
            )
            if ref_count >= 2:  # 被引用多次但不存在
                issues["hint"].append({
                    "type": "待建链接",
                    "link": link,
                    "detail": f"被 {ref_count} 个页面引用，建议创建"
                })
            else:
                issues["info"].append({
                    "type": "未解析链接",
                    "link": link,
                    "detail": "被引用但对应页面不存在"
                })

    # ---- 检查 3: Frontmatter 完整性 ----
    required_fields = ["title", "type", "status"]
    for fp in all_files:
        try:
            content = open(fp, encoding="utf-8").read()
            fm = extract_frontmatter(content)
            
            missing = [f for f in required_fields if f not in fm]
            if missing:
                issues["info"].append({
                    "type": "Frontmatter 不完整",
                    "file": fp,
                    "detail": f"缺少字段: {', '.join(missing)}"
                })
            
            # 状态检查
            status = fm.get("status", "")
            if status == "draft":
                issues["info"].append({
                    "type": "草稿状态",
                    "file": fp,
                    "detail": "页面仍为草稿状态，可能需要完善"
                })
        except Exception:
            pass

    # ---- 检查 4: 缺少摘要或来源 ----
    for fp in all_files:
        try:
            content = open(fp, encoding="utf-8").read()
            
            if "## 摘要" not in content and "## Summary" not in content:
                issues["info"].append({
                    "type": "缺少摘要",
                    "file": fp,
                    "detail": "页面缺少摘要部分"
                })
            
            if "## 来源" not in content and "## 来源引用" not in content:
                issues["warning"].append({
                    "type": "缺少来源引用",
                    "file": fp,
                    "detail": "页面缺少来源引用，无法追溯信息出处"
                })
        except Exception:
            pass

    # ---- 输出报告 ----
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    print(f"  扫描时间: {now}")
    print(f"  扫描范围: {total_pages} 个 Wiki 页面")
    print(f"           ({len(concept_files)} 概念 + {len(entity_files)} 实体 + {len(synthesis_files)} 综合)\n")
    
    # 问题统计
    severity_order = [("severe", "🔴", "严重"), ("warning", "🟠", "中等"), 
                       ("info", "🔵", "低"), ("hint", "🟢", "提示")]
    
    print(f"{Colors.BOLD}  问题汇总{Colors.END}")
    print(f"  {'─'*45}")
    
    total_issues = 0
    for key, icon, label in severity_order:
        count = len(issues[key])
        total_issues += count
        status_icon = icon
        if count == 0:
            status_icon = "✅"
        print(f"  {status_icon} {label}: {count}")
    
    print(f"\n  总计: {total_issues} 个问题\n")
    
    # 详细问题
    if total_issues > 0:
        print(f"{Colors.BOLD}  详细问题{Colors.END}")
        
        for key, icon, label in severity_order:
            if not issues[key]:
                continue
            
            print(f"\n  {icon} {label} ({len(issues[key])})")
            print(f"  {'─' * 40}")
            
            for i, issue in enumerate(issues[key], 1):
                if "file" in issue:
                    rel_path = os.path.relpath(issue["file"], root)
                    print(f"  {i}. [{issue['type']}] {rel_path}")
                elif "link" in issue:
                    print(f"  {i}. [{issue['type'}] [[{issue['link']}]]")
                
                detail = issue.get("detail", "")
                if detail:
                    print(f"     → {detail}")

    # 健康评分
    max_score = total_pages * 10  # 每页满分 10 分
    deduction = total_issues * 2
    score = max(0, min(100, max_score - deduction)) if max_score > 0 else 100
    
    score_color = Colors.GREEN if score >= 80 else (Colors.YELLOW if score >= 60 else Colors.RED)
    print(f"\n{'─'*45}")
    print(f"  📊 健康评分: {score_color}{score}/100{Colors.END}")
    
    if score >= 80:
        print(f"  ✅ 知识库状态良好！")
    elif score >= 60:
        print(f"  ⚠️  有一些小问题需要处理。")
    else:
        print(f"  ❌ 存在较多问题，建议执行维护。")


# ============================================================
# 命令：stats - 统计信息
# ============================================================

def cmd_stats(wiki_root=None):
    """显示知识库统计信息"""

    root = wiki_root or find_wiki_root()
    if not root:
        print("❌ 未找到 CAM 项目根目录")
        sys.exit(1)

    concept_files = get_all_md_files(os.path.join(root, CONCEPT_DIR))
    entity_files = get_all_md_files(os.path.join(root, ENTITY_DIR))
    synthesis_files = get_all_md_files(os.path.join(root, SYNTHESIS_DIR))
    raw_files = get_all_md_files(os.path.join(root, RAW_DIR))

    all_wiki = concept_files + entity_files + synthesis_files
    
    # 统计链接
    total_links = 0
    total_words = 0
    tags_set = set()

    for fp in all_wiki:
        try:
            content = open(fp, encoding="utf-8").read()
            total_links += len(extract_internal_links(content))
            total_words += len(content.split())
            
            # 提取标签
            fm = extract_frontmatter(content)
            tags = fm.get("tags", [])
            if isinstance(tags, list):
                tags_set.update(tags)
        except Exception:
            pass

    print(f"{Colors.BOLD}📊 CAM 统计{Colors.END}")
    print(f"   项目: {root}\n")

    print(f"  📁 页面数量:")
    print(f"     概念页 (concept/):    {len(concept_files):>4}")
    print(f"     实体页 (entity/):     {len(entity_files):>4}")
    print(f"     综合页 (synthesis/):  {len(synthesis_files):>4}")
    print(f"     ─────────────────────")
    print(f"     合计:                 {len(all_wiki):>4}")

    print(f"\n  📥 原始资料: {len(raw_files)} 个文件")

    print(f"\n  🔗 关联情况:")
    print(f"     双链总数:       {total_links}")
    print(f"     平均每页链接:   {total_links / len(all_wiki):.1f}" if all_wiki else "     平均每页链接:   N/A")
    print(f"     总字数:         ~{total_words:,}")
    print(f"     标签种类:       {len(tags_set)}")

    print(f"\n  🏷️ 标签云:")
    if tags_set:
        tag_str = "  ".join(f"[{t}]" for t in sorted(tags_set)[:20])
        print(f"     {tag_str}")
        if len(tags_set) > 20:
            print(f"     ... 等 {len(tags_set)} 个标签")
    else:
        print(f"     (暂无标签)")

    # 最近修改
    print(f"\n  🕒 最近更新:")
    if all_wiki:
        recent = sorted(all_wiki, key=lambda f: os.path.getmtime(f), reverse=True)[:5]
        for fp in recent:
            mtime = datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M")
            rel = os.path.relpath(fp, root)
            print(f"     {mtime}  {rel}")
    else:
        print(f"     (暂无内容)")


# ============================================================
# 命令：check-raw - 检查未处理的 raw 文件
# ============================================================

def cmd_check_raw(wiki_root=None):
    """列出 raw/ 中未被处理的文件"""

    root = wiki_root or find_wiki_root()
    if not root:
        print("❌ 未找到 CAM 项目根目录")
        sys.exit(1)

    raw_dir = os.path.join(root, RAW_DIR)
    if not os.path.exists(raw_dir):
        print(f"ℹ️  raw/ 目录不存在")
        return

    raw_files = [
        f for f in os.listdir(raw_dir) 
        if not f.startswith(".") and f != ".gitkeep"
    ]

    # 从 changelog 获取已处理文件列表
    processed = set()
    changelog_path = os.path.join(root, CHANGELOG_FILE)
    if os.path.exists(changelog_path):
        try:
            content = open(changelog_path, encoding="utf-8").read()
            # 简单提取已处理文件名
            for line in content.split("\n"):
                if "raw/" in line or "INGEST" in line:
                    pass  # AI 维护的详细记录
        except Exception:
            pass

    print(f"{Colors.BOLD}📥 Raw 资料清单{Colors.END}\n")

    if not raw_files:
        print("  📭 raw/ 目录为空")
        print("\n  💡 将原始资料放入此目录后执行 INGEST 操作。")
        return

    total_size = 0
    for i, fname in enumerate(sorted(raw_files), 1):
        fpath = os.path.join(raw_dir, fname)
        size = os.path.getsize(fpath)
        total_size += size
        size_str = f"{size/1024:.1f}KB" if size > 1024 else f"{size}B"

        # 判断类型图标
        ext = os.path.splitext(fname)[1].lower()
        type_icon = {"md": "📝", "txt": "📄", "pdf": "📕", 
                     "png": "🖼️", "jpg": "🖼️", "jpeg": "🖼️"}.get(ext, "📎")

        marker = "⬅️ 新"  # 默认标记为新
        print(f"  {i}. {type_icon} {fname:<40} {size_str:>8}  {marker}")

    print(f"\n  共 {len(raw_files)} 个文件, 总大小: {total_size/1024:.1f} KB")
    print(f"\n  💡 对 AI 说: \"请处理 raw/ 中的新资料\" 或 \"执行 INGEST\"")


# ============================================================
# 主入口
# ============================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print(f"\n可用命令:")
        print(f"  init          - 初始化新项目")
        print(f"  lint [路径]   - Wiki 健康检查")
        print(f"  stats [路径]  - 统计信息")
        print(f"  check-raw     - 查看 raw/ 未处理文件")
        sys.exit(0)

    command = sys.argv[1].lower()
    args = sys.argv[2:]

    if command == "init":
        path = args[0] if args else "."
        cmd_init(path)
    elif command == "lint":
        path = args[0] if args else None
        cmd_lint(path)
    elif command == "stats":
        path = args[0] if args else None
        cmd_stats(path)
    elif command == "check-raw":
        path = args[0] if args else None
        cmd_check_raw(path)
    else:
        print(f"未知命令: {command}")
        print(f"运行 `python cam_tool.py` 查看帮助")
        sys.exit(1)


if __name__ == "__main__":
    main()
