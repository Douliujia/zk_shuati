#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 PDF 解析选择题，生成带 LaTeX / 公式截图的 JSON 题库。"""

from __future__ import annotations

import json
import re
import sys
from html import unescape
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / "自动控制原理选择题（100题）.pdf"
OUT_JSON = ROOT / "data" / "questions.json"
FORMULA_DIR = ROOT / "data" / "formulas"

SYMBOL_MAP = {
    "\uf02b": "+",
    "\uf02d": "-",
    "\uf03d": "=",
    "\uf0b4": "*",
    "\uf028": "(",
    "\uf029": ")",
    "\uf0a5": r"\infty",
    "\uf061": r"\alpha",
    "\uf062": r"\beta",
    "\uf07a": r"\omega",
    "\uf074": r"\tau",
    "\u2212": "-",
    "\u221e": r"\infty",
    "\u03b6": r"\zeta",
    "\u03c9": r"\omega",
    "\u03b1": r"\alpha",
    "\u03b2": r"\beta",
    "\u03b3": r"\gamma",
    "\u03c4": r"\tau",
    "\u0394": r"\Delta",
    "\u2220": r"\angle",
    "\u2211": r"\sum",
}

GREEK_INLINE = {
    "ζ": r"\zeta",
    "ω": r"\omega",
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "τ": r"\tau",
    "Δ": r"\Delta",
    "∠": r"\angle",
    "∞": r"\infty",
    "±": r"\pm",
    "°": r"^\circ",
}

ANSWER_RE = re.compile(r"[（(]\s*([A-Da-d])\s*[）)]?")
QUESTION_SPLIT_RE = re.compile(
    r"(?="
    r"\n\s*(?:[1-9]\d{0,2}|100)\s*[\．\.]\s*(?!\d)"
    r"|\n\s*(?:[1-9]\d{0,2}|100)\s+(?=[\u4e00-\u9fff])"
    r")"
)
QUESTION_HEAD_RE = re.compile(
    r"^\s*(\d{1,3})(?:\s*[\．\.]\s*|\s+(?=[\u4e00-\u9fff]))"
)
# 选项标记：A. / A． / A、 50 / B 、；排除极点 A、B
OPTION_MARK = r"(?:[\.．]|" + "\u3001" + r"(?![A-D]))"
OPTION_ITEM_RE = re.compile(
    rf"([A-D])\s*{OPTION_MARK}\s*(.*?)(?=(?:\s+[A-D]\s*{OPTION_MARK})|$)",
    re.DOTALL,
)
OPTION_MARKER_FIND = re.compile(rf"(?:^|\n)\s*([A-D])\s*{OPTION_MARK}")


def parse_style(style: str) -> dict:
    result = {}
    for part in style.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            result[k.strip()] = v.strip()
    return result


def clean_symbol_text(text: str) -> str:
    for k, v in SYMBOL_MAP.items():
        text = text.replace(k, v)
    return re.sub(r"[ \t]+", " ", text).strip()


def text_to_latex_inline(text: str) -> str:
    text = clean_symbol_text(text)
    text = ANSWER_RE.sub("（　）", text, count=1)
    for ch, latex in GREEK_INLINE.items():
        text = text.replace(ch, f"${latex}$")
    text = text.replace("$\\omega$n", "$\\omega_n$")
    text = text.replace("ess", "$e_{ss}$")
    for token in ["G(s)H(s)", "G_c(s)", "G_B(s)", "G(s)", "H(s)", "E(s)"]:
        text = text.replace(token, f"${token}$")
    text = text.replace("+∞", "$+\\infty$")
    text = re.sub(r"(\d+)°", lambda m: f"${m.group(1)}^\\circ$", text)
    return text


def extract_answer(text: str) -> Tuple[str, Optional[str]]:
    m = ANSWER_RE.search(text)
    if not m:
        return text, None
    cleaned = ANSWER_RE.sub("（　）", text, count=1)
    return cleaned, m.group(1).upper()


def parse_options(text: str) -> Dict[str, str]:
    text = clean_symbol_text(text)
    opts: Dict[str, str] = {}
    for m in OPTION_ITEM_RE.finditer(text):
        label = m.group(1).upper()
        val = m.group(2).strip()
        val = re.sub(r"\s+", " ", val)
        if val:
            opts[label] = val
    return opts


def split_stem_and_options(block: str) -> Tuple[str, str]:
    candidates: List[Tuple[int, str, int, bool]] = []
    for m in OPTION_MARKER_FIND.finditer(block):
        opt_text = block[m.start() :].strip()
        opts = parse_options(opt_text)
        if len(opts) < 2:
            continue
        complete = set(opts.keys()) == {"A", "B", "C", "D"}
        candidates.append((m.start(), opt_text, len(opts), complete))

    if not candidates:
        return block, ""

    complete = [c for c in candidates if c[3]]
    if complete:
        start, opt_text, _, _ = min(complete, key=lambda x: x[0])
    else:
        start, opt_text, _, _ = max(candidates, key=lambda x: (x[2], -x[0]))
    return block[:start].strip(), opt_text


def build_option_segments(
    val: str,
    qid: int,
    label: str,
    img_counter: List[int],
    page: fitz.Page,
    lines: List[dict],
    y0: float,
    y1: float,
) -> List[dict]:
    val = val.strip()
    formula_like = bool(re.search(r"[=+]|s\s*s|s\)|\(\s*1\)", val)) and len(re.findall(r"[\u4e00-\u9fff]", val)) < 4
    if re.search(r"[\u4e00-\u9fff]", val) and not formula_like:
        return [{"type": "text", "content": text_to_latex_inline(val)}]

    bbox = find_formula_bbox_for_text(val, lines, page.rect, y0, y1)
    if bbox and bbox.width > 5 and bbox.height > 5:
        img_counter[0] += 1
        rel = crop_formula_image(page, bbox, f"q{qid}_opt_{label}_{img_counter[0]}")
        return [{"type": "image", "src": rel, "alt": f"选项{label}"}]

    if formula_like:
        img_counter[0] += 1
        rel = crop_formula_between_lines(page, lines, y0, y1, f"q{qid}_opt_{label}_{img_counter[0]}")
        if rel:
            return [{"type": "image", "src": rel, "alt": f"选项{label}"}]

    return [{"type": "text", "content": text_to_latex_inline(val)}]


def extract_lines(page: fitz.Page) -> List[dict]:
    soup = BeautifulSoup(page.get_text("html"), "html.parser")
    raw: Dict[float, dict] = {}
    for p in soup.find_all("p"):
        st = parse_style(p.get("style", ""))
        top = float(st.get("top", "0").replace("pt", ""))
        left = float(st.get("left", "0").replace("pt", ""))
        texts: List[str] = []
        math = False
        max_size = 10.0
        max_right = left
        for sp in p.find_all("span"):
            sst = parse_style(sp.get("style", ""))
            t = clean_symbol_text(unescape(sp.get_text()))
            font = sst.get("font-family", "").lower()
            size = float(sst.get("font-size", "10").replace("pt", ""))
            sp_left = float(sst.get("left", str(left)).replace("pt", "")) if "left" in sst else left
            max_size = max(max_size, size)
            max_right = max(max_right, sp_left + len(t) * size * 0.55)
            if "symbol" in font or sp.find("i") is not None:
                math = True
            texts.append(t)
        text = clean_symbol_text("".join(texts))
        if not text:
            continue
        if top not in raw:
            raw[top] = {
                "top": top,
                "left": left,
                "right": max_right,
                "size": max_size,
                "text": text,
                "math": math,
            }
        else:
            raw[top]["text"] += text
            raw[top]["math"] = raw[top]["math"] or math
            raw[top]["right"] = max(raw[top]["right"], max_right)
            raw[top]["size"] = max(raw[top]["size"], max_size)
    return sorted(raw.values(), key=lambda x: (x["top"], x["left"]))


def line_bbox(line: dict, page_rect: fitz.Rect) -> fitz.Rect:
    size = line.get("size", 12)
    height = max(size * 1.35, 14)
    x0 = max(0, line["left"] - 4)
    y0 = max(0, line["top"] - 3)
    x1 = min(page_rect.width, line.get("right", line["left"] + 80) + 8)
    y1 = min(page_rect.height, line["top"] + height + 6)
    return fitz.Rect(x0, y0, x1, y1)


def merge_bbox(rects: List[fitz.Rect]) -> fitz.Rect:
    return fitz.Rect(
        min(r.x0 for r in rects),
        min(r.y0 for r in rects),
        max(r.x1 for r in rects),
        max(r.y1 for r in rects),
    )


def crop_formula_image(page: fitz.Page, bbox: fitz.Rect, name: str) -> str:
    FORMULA_DIR.mkdir(parents=True, exist_ok=True)
    rel = f"formulas/{name}.png"
    clip = (bbox + (-12, -12, 12, 12)) & page.rect
    pix = page.get_pixmap(matrix=fitz.Matrix(6, 6), clip=clip, alpha=False)
    pix.save(str(FORMULA_DIR / f"{name}.png"))
    return rel


def find_math_lines_in_range(lines: List[dict], y0: float, y1: float) -> List[dict]:
    return [ln for ln in lines if y0 <= ln["top"] <= y1 and (ln.get("math") or ln["left"] > 130)]


def find_question_y_range(lines: List[dict], qid: int, block: str) -> Tuple[float, float]:
    """根据页内行定位题目纵坐标范围（题干到选项前）。"""
    head = block.split("\n", 1)[0][:20]
    start_top = None
    end_top = None
    for i, ln in enumerate(lines):
        if start_top is None and re.match(
            rf"^\s*{qid}(?:\s*[\．\.]\s*|\s+(?=[\u4e00-\u9fff]))", ln["text"]
        ):
            start_top = ln["top"]
            continue
        if start_top is not None and OPTION_MARKER_FIND.search(ln["text"]):
            end_top = ln["top"]
            break
        if start_top is not None and re.match(rf"^\s*{qid + 1}\s*[\．\.]", ln["text"]):
            end_top = ln["top"]
            break
    if start_top is None:
        return 0, page_max(lines)
    if end_top is None:
        end_top = start_top + 120
    return start_top, end_top - 2


def page_max(lines: List[dict]) -> float:
    return max((ln["top"] for ln in lines), default=9999)


def crop_formula_between_lines(page: fitz.Page, lines: List[dict], y0: float, y1: float, name: str) -> Optional[str]:
    math_lines = find_math_lines_in_range(lines, y0, y1)
    if not math_lines:
        return None
    bbox = merge_bbox([line_bbox(ln, page.rect) for ln in math_lines])
    # 分式等竖排公式：适当放宽宽度
    bbox = fitz.Rect(max(0, min(bbox.x0, 160) - 8), bbox.y0, min(page.rect.width, max(bbox.x1, 320)), bbox.y1)
    if bbox.width < 8 or bbox.height < 8:
        return None
    return crop_formula_image(page, bbox, name)


def find_formula_bbox_for_text(
    fragment: str,
    lines: List[dict],
    page_rect: fitz.Rect,
    y0: float = 0,
    y1: float = 9999,
) -> Optional[fitz.Rect]:
    key = re.sub(r"\s+", "", fragment)[:10]
    if len(key) < 2:
        return None
    rects = []
    for ln in lines:
        if ln["top"] < y0 or ln["top"] > y1:
            continue
        if ln.get("math") or ln["left"] > 130:
            compact = re.sub(r"\s+", "", ln["text"])
            if key in compact or (len(compact) >= 3 and compact in key):
                rects.append(line_bbox(ln, page_rect))
    if rects:
        return merge_bbox(rects)
    return None


def extract_formula_segments(
    page: fitz.Page,
    lines: List[dict],
    stem: str,
    qid: int,
    counter: List[int],
    block: str,
) -> Tuple[List[dict], Optional[str]]:
    segments: List[dict] = []
    head = QUESTION_HEAD_RE.sub("", stem, count=1).strip()
    head, answer_from_head = extract_answer(head)

    y0, y1 = find_question_y_range(lines, qid, block)

    chunks = [c.strip() for c in re.split(r"\n+", head) if c.strip()]
    text_parts: List[str] = []
    has_formula = False

    for chunk in chunks:
        is_cjk = re.search(r"[\u4e00-\u9fff]{2,}", chunk)
        is_math_only = not is_cjk or re.match(r"^[\d\s+\-*/=().sSGDTK]+$", chunk)
        if is_cjk and not is_math_only:
            text_parts.append(chunk)
        elif chunk and not is_cjk:
            has_formula = True

    if text_parts:
        merged = " ".join(text_parts)
        segments.append({"type": "text", "content": text_to_latex_inline(merged)})

    if has_formula:
        counter[0] += 1
        rel = crop_formula_between_lines(page, lines, y0 + 8, y1, f"q{qid}_f_{counter[0]}")
        if rel:
            segments.append({"type": "image", "src": rel, "alt": "公式"})
        elif not segments:
            segments.append({"type": "text", "content": text_to_latex_inline(head)})
    elif not segments:
        segments.append({"type": "text", "content": text_to_latex_inline(head)})

    return segments, answer_from_head


def find_page_for_question(qid: int, block: str, page_texts: List[str]) -> int:
    snippet = block[:40].strip()
    for i, text in enumerate(page_texts):
        if snippet and snippet in text:
            return i
    return min(max(qid // 10 - 1, 0), len(page_texts) - 1)


def parse_questions_from_text(full_text: str) -> Dict[int, str]:
    chunks = QUESTION_SPLIT_RE.split("\n" + full_text)
    result: Dict[int, str] = {}
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        m = QUESTION_HEAD_RE.match(chunk)
        if not m:
            continue
        qid = int(m.group(1))
        if qid < 1 or qid > 100:
            continue
        if qid not in result or len(chunk) > len(result[qid]):
            result[qid] = chunk
    return result


def main() -> int:
    if not PDF_PATH.exists():
        print(f"找不到 PDF: {PDF_PATH}", file=sys.stderr)
        return 1

    doc = fitz.open(str(PDF_PATH))
    page_texts: List[str] = []
    page_lines: List[List[dict]] = []
    for page in doc:
        page_texts.append(page.get_text())
        page_lines.append(extract_lines(page))
    doc.close()

    full_text = "\n".join(page_texts)
    blocks = parse_questions_from_text(full_text)

    questions: List[dict] = []
    img_counter = [0]

    doc = fitz.open(str(PDF_PATH))
    for qid in range(1, 101):
        block = blocks.get(qid)
        if not block:
            continue

        stem, opt_text = split_stem_and_options(block)
        raw_opts = parse_options(opt_text)
        if len(raw_opts) < 2:
            continue

        _, answer = extract_answer(block)
        page_idx = find_page_for_question(qid, block, page_texts)
        page = doc[page_idx]
        lines = page_lines[page_idx]

        segments, ans2 = extract_formula_segments(page, lines, stem, qid, img_counter, block)
        if not answer:
            answer = ans2

        y0, y1 = find_question_y_range(lines, qid, block)
        options = {}
        for label, val in raw_opts.items():
            options[label] = build_option_segments(val, qid, label, img_counter, page, lines, y0, y1)

        questions.append(
            {
                "id": qid,
                "page": page_idx + 1,
                "segments": segments,
                "options": options,
                "answer": answer or "?",
            }
        )
    doc.close()

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "title": "自动控制原理选择题（100题）",
        "source": PDF_PATH.name,
        "total": len(questions),
        "questions": questions,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    missing = [i for i in range(1, 101) if i not in {q["id"] for q in questions}]
    unknown = [q["id"] for q in questions if q["answer"] == "?"]
    print(f"解析完成: {len(questions)} 题 -> {OUT_JSON}")
    if missing:
        print(f"缺失题号: {missing}")
    if unknown:
        print(f"未识别答案: {unknown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
