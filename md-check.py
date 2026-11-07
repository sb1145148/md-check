"""检查一份 Markdown 文件的常见问题（只读，不改文件）。

用法：python check-md.py <文件路径>
"""
import re
import sys
import os
from collections import Counter


def check(path: str) -> int:
    problems = []
    warns = []

    raw = open(path, "rb").read()
    if raw[:3] == b"\xef\xbb\xbf":
        warns.append("文件带 UTF-8 BOM（大多没问题，但某些工具会多显示一个字符）")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        print(f"❌ 不是合法 UTF-8：{e}")
        return 1

    lines = text.split("\n")
    print(f"文件：{path}")
    print(f"大小：{os.path.getsize(path)} B | 行数：{len(lines)} | 字符：{len(text)}")

    # ---------- 1. 代码块 ----------
    fences = [i for i, l in enumerate(lines, 1) if l.lstrip().startswith("```")]
    if len(fences) % 2:
        problems.append(f"代码块围栏 {len(fences)} 个（奇数）—— 最后一个从第 {fences[-1]} 行开始没闭合")
    else:
        print(f"✅ 代码块：{len(fences) // 2} 对，闭合正常")

    fence_set = set()
    inside = False
    start = 0
    for i, l in enumerate(lines, 1):
        if l.lstrip().startswith("```"):
            if not inside:
                inside = True
                start = i
            else:
                inside = False
                for k in range(start, i + 1):
                    fence_set.add(k)
    # 没有语言标注的围栏
    for i in fences:
        line = lines[i - 1].strip()
        if line == "```" and lines[i].strip() and not re.match(r"^\s*(###?|\||-|\d)", lines[i]):
            pass

    # ---------- 2. 标题层级 ----------
    heads = [(i, l) for i, l in enumerate(lines, 1) if i not in fence_set and re.match(r"^#{1,6} ", l)]
    levels = [len(l.split(" ")[0]) for _, l in heads]
    prev = 0
    for (i, l), lv in zip(heads, levels):
        if prev and lv > prev + 1:
            warns.append(f"第 {i} 行标题跳级：H{prev} → H{lv}（「{l[:30]}」）")
        prev = lv
    print(f"✅ 标题：{len(heads)} 个（H1 {levels.count(1)} / H2 {levels.count(2)} / H3 {levels.count(3)} / H4 {levels.count(4)}）")
    dup = [h for h, c in Counter(l for _, l in heads).items() if c > 1]
    if dup:
        warns.append(f"重复标题：{dup[:3]}")

    # ---------- 3. 表格 ----------
    table_issues = 0
    i = 0
    while i < len(lines) - 1:
        line = lines[i]
        nxt = lines[i + 1]
        if line.strip().startswith("|") and re.match(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", nxt):
            def cols_of(s):
                return re.split(r"(?<!\\)\|", s.strip().strip("|"))
            header = cols_of(line)
            sep = cols_of(nxt)
            if len(header) != len(sep):
                problems.append(f"第 {i+1} 行表格：表头 {len(header)} 列，分隔行 {len(sep)} 列")
                table_issues += 1
            if "\t" in line or "\t" in nxt:
                warns.append(f"第 {i+1} 行表格里有 Tab（列宽会歪）")
            # 检查后续数据行列数
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                cols = cols_of(lines[j])
                if len(cols) != len(header):
                    warns.append(f"第 {j+1} 行表格：{len(cols)} 列，与表头 {len(header)} 列不一致")
                j += 1
            i = j
            continue
        i += 1
    print(f"✅ 表格：检查完毕（结构问题 {table_issues} 处）")

    # ---------- 4. 任务列表 ----------
    ok = len(re.findall(r"^- \[ \] ", text, re.M)) + len(re.findall(r"^- \[x\] ", text, re.M))
    bad = 0
    for i, l in enumerate(lines, 1):
        if l.startswith("- [") and not re.match(r"^- \[[ x]\] .", l):
            bad += 1
            if bad <= 5:
                warns.append(f"第 {i} 行任务列表写法不标准：{l[:40]!r}")
    n_open = len(re.findall(r"^- \[ \] ", text, re.M))
    n_done = len(re.findall(r"^- \[x\] ", text, re.M))
    print(f"✅ 任务列表：标准 {ok} 条（未打勾 {n_open} / 已打勾 {n_done}），不标准 {bad} 条")

    # ---------- 5. 强调符号配对 ----------
    for i, l in enumerate(lines, 1):
        if i in fence_set:
            continue
        if l.count("**") % 2:
            # 允许行内 `**` 作为代码示例
            if "`**`" in l:
                continue
            problems.append(f"第 {i} 行加粗未闭合（** 出现 {l.count('**')} 次）：{l[:50]}")
    print("✅ 加粗配对：检查完毕")

    # ---------- 6. 行尾空白 / 混合缩进 ----------
    trailing = [i for i, l in enumerate(lines, 1) if l.rstrip() != l and l.strip()]
    if trailing:
        warns.append(f"{len(trailing)} 行有行尾空白（第 {trailing[:5]} 行…）")
    tabs = [i for i, l in enumerate(lines, 1) if "\t" in l and i not in fence_set]
    if tabs:
        warns.append(f"{len(tabs)} 行含 Tab（第 {tabs[:5]} 行…）")

    # ---------- 7. 链接 ----------
    base = os.path.dirname(os.path.abspath(path))
    broken = []
    nofence = "\n".join(l for i, l in enumerate(lines, 1) if i not in fence_set)
    for m in re.finditer(r"\[([^\]]*)\]\(([^)]+)\)", nofence):
        target = m.group(2).strip()
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        local = target.split("#")[0]
        if not local:
            continue
        full = os.path.normpath(os.path.join(base, local.replace("/", os.sep)))
        if not os.path.exists(full):
            broken.append((m.group(1)[:20], target))
    if broken:
        for name, t in broken[:8]:
            problems.append(f"相对链接指向不存在的文件：[{name}]({t})")
    print(f"✅ 链接：检查完毕（失效相对链接 {len(broken)} 个）")

    # ---------- 8. 列表缩进 ----------
    for i, l in enumerate(lines, 1):
        if i in fence_set:
            continue
        m = re.match(r"^( +)[-*+] ", l)
        if m and len(m.group(1)) % 2:
            warns.append(f"第 {i} 行列表缩进 {len(m.group(1))} 个空格（奇数，可能层级错乱）")

    # ---------- 输出 ----------
    print()
    if problems:
        print(f"❌ 需要修的问题（{len(problems)} 个）：")
        for p in problems:
            print(f"   · {p}")
    else:
        print("✅ 没有结构性问题")

    if warns:
        print(f"\n⚠️ 建议关注（{len(warns)} 条）：")
        for w in warns[:12]:
            print(f"   · {w}")
        if len(warns) > 12:
            print(f"   … 还有 {len(warns) - 12} 条")

    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python check-md.py <markdown 文件>")
        sys.exit(2)
    sys.exit(check(sys.argv[1]))
