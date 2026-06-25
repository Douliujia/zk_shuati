#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 GitHub Pages 静态站点到 docs/ 目录。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
JSON_FILE = DATA_DIR / "questions.json"


def main() -> int:
    if not JSON_FILE.exists():
        print("未找到 data/questions.json，请先运行：python scripts/parse_pdf.py", file=sys.stderr)
        return 1

    if DOCS_DIR.exists():
        shutil.rmtree(DOCS_DIR)
    DOCS_DIR.mkdir(parents=True)

    for name in ("index.html", "style.css", "app.js"):
        shutil.copy2(APP_DIR / name, DOCS_DIR / name)

    shutil.copytree(DATA_DIR, DOCS_DIR / "data")
    (DOCS_DIR / ".nojekyll").touch()

    formula_count = len(list((DOCS_DIR / "data" / "formulas").glob("*.png")))
    print(f"已生成 GitHub Pages 站点 -> {DOCS_DIR}")
    print(f"  页面: index.html, style.css, app.js")
    print(f"  题库: questions.json, 公式图 {formula_count} 张")
    print()
    print("下一步：")
    print("  1. git add docs && git commit -m \"deploy: update github pages\"")
    print("  2. git push（推送到 GitHub 仓库）")
    print("  3. GitHub 仓库 → Settings → Pages → Branch 选 main，Folder 选 /docs")
    print("  4. 部署完成后访问：https://<用户名>.github.io/<仓库名>/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
