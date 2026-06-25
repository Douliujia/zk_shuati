#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 PDF 解析选择题：纯文字用文本，公式/图形用 PDF 原图截图。"""

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

CONTENT_MARGIN = 72.0
CROP_MATRIX = fitz.Matrix(8, 8)
CROP_PAD = (-8, -6, 8, 6)

SYMBOL_MAP = {
    "\uf02b": "+",
    "\uf02d": "-",
    "\uf03d": "=",
    "\uf0b4": "*",
    "\uf028": "(",
    "\uf029": ")",
    "\uf0a5": "∞",
    "\uf061": "α",
    "\uf062": "β",
    "\uf07a": "ω",
    "\uf074": "τ",
    "\u2212": "-",
    "\u221e": "∞",
    "\u03b6": "ζ",
    "\u03c9": "ω",
    "\u03b1": "α",
    "\u03b2": "β",
    "\u03b3": "γ",
    "\u03c4": "τ",
    "\u0394": "Δ",
    "\u2220": "∠",
    "\u2211": "∑",
    "\u00b1": "±",
}

# 保留 LaTeX 名称到 Unicode 的兜底（PDF 文本偶发导出为 \omega 等形式）
LATEX_NAME_TO_UNICODE = {
    r"\omega": "ω",
    r"\Omega": "Ω",
    r"\zeta": "ζ",
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\tau": "τ",
    r"\Delta": "Δ",
    r"\infty": "∞",
    r"\angle": "∠",
    r"\pm": "±",
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


def text_to_display(text: str) -> str:
    """将 PDF 提取文本转为页面可显示的纯文本（希腊字母等用 Unicode）。"""
    text = clean_symbol_text(text)
    for name, ch in LATEX_NAME_TO_UNICODE.items():
        text = text.replace(name, ch)
    text = ANSWER_RE.sub("（　）", text, count=1)
    text = text.replace("ωn", "ωₙ").replace("ω n", "ωₙ")
    text = re.sub(r"(\d+)°", r"\1°", text)
    return text


def is_text_option(val: str) -> bool:
    """纯文字/数字选项，无需截图。"""
    val = clean_symbol_text(val.strip())
    if re.fullmatch(r"\d+", val):
        return True
    if not re.search(r"[\u4e00-\u9fff]", val):
        return False
    return not is_formula_content(val)


def is_formula_content(text: str) -> bool:
    """内容含公式、分式或 PDF 无法可靠还原为文字的符号。"""
    if any("\uf000" <= ch <= "\uf0ff" for ch in text):
        return True
    if re.search(
        r"为\s*[，,]\s*则|函数为\s*[，,]|方程为\s*[，,]|传递函数\s*[，,]|传\s*递\s*函\s*数为\s*[，,]",
        text,
    ):
        return True
    if re.search(r"[=+]|G\s*\(|H\s*\(|\\frac|/\s*s\b|s\^|s\+", text):
        cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
        if cjk < 4:
            return True
    # 以符号/字母为主、几乎无中文的片段
    if len(text.strip()) > 1 and len(re.findall(r"[\u4e00-\u9fff]", text)) < 2:
        if re.search(r"[=+\-*/\(\)sSGH]", text):
            return True
    return False


def stem_needs_formula_image(head: str, stem_lines: List[dict]) -> bool:
    if is_formula_content(head):
        return True
    if re.search(r"为\s*[，,]|函数为\s*[，,]|方程为\s*[，,]", head):
        return True
    for ln in stem_lines:
        text = ln.get("text", "")
        if ln.get("math") and ln.get("left", 0) > 120:
            return True
        if not re.search(r"[\u4e00-\u9fff]{2,}", text) and re.search(r"[=+\-*/\(\)sS]", text):
            return True
    return False


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
    markers: Dict[str, fitz.Rect],
    opt_y1: float,
) -> List[dict]:
    val = clean_symbol_text(val.strip())
    # 纯文字选项一律用文本，不截图
    if is_text_option(val) or not is_formula_content(val):
        return [{"type": "text", "content": text_to_display(val)}]

    img_counter[0] += 1
    rel = crop_option_on_page(
        page, label, markers, opt_y1, f"q{qid}_opt_{label}_{img_counter[0]}"
    )
    if rel:
        return [{"type": "image", "src": rel, "alt": f"选项{label}"}]
    return [{"type": "text", "content": text_to_display(val)}]


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
    height = max(size * 1.45, 15)
    x0 = max(0, line["left"] - 4)
    y0 = max(0, line["top"] - 3)
    text = line.get("text", "")
    cjk = bool(re.search(r"[\u4e00-\u9fff]", text))
    char_w = size * (0.92 if cjk else 0.58)
    est_right = line["left"] + max(len(text) * char_w, size * 2)
    x1 = min(page_rect.width, max(line.get("right", est_right), est_right) + 10)
    y1 = min(page_rect.height, line["top"] + height + 4)
    return fitz.Rect(x0, y0, x1, y1)


def merge_bbox(rects: List[fitz.Rect]) -> fitz.Rect:
    return fitz.Rect(
        min(r.x0 for r in rects),
        min(r.y0 for r in rects),
        max(r.x1 for r in rects),
        max(r.y1 for r in rects),
    )


def answer_search_patterns(answer: str) -> List[str]:
    a = answer.upper()
    al = a.lower()
    return [
        f"({a})",
        f"（{a}）",
        f"({a}）",
        f"（{a})",
        f"( {a})",
        f"（ {a}）",
        f"( {a}）",
        f"（ {a})",
        f"({al})",
        f"（{al}）",
    ]


def find_answer_hits(
    page: fitz.Page, answer: Optional[str], bbox: Optional[fitz.Rect] = None
) -> List[fitz.Rect]:
    if not answer or answer == "?":
        return []
    hits: List[fitz.Rect] = []
    for pat in answer_search_patterns(answer):
        for h in page.search_for(pat):
            if bbox is None or bbox.intersects(h):
                hits.append(h)
    return hits


def shrink_bbox_before_answer(
    page: fitz.Page, bbox: fitz.Rect, answer: Optional[str]
) -> fitz.Rect:
    hits = find_answer_hits(page, answer, bbox)
    if not hits:
        return bbox
    cut = min(h.x0 for h in hits) - 5
    if cut > bbox.x0 + 24:
        return fitz.Rect(bbox.x0, bbox.y0, cut, bbox.y1)
    return bbox


def iter_span_rects(page: fitz.Page) -> List[Tuple[str, fitz.Rect]]:
    items: List[Tuple[str, fitz.Rect]] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span.get("text", "")
                if text and text.strip():
                    items.append((text, fitz.Rect(span["bbox"])))
    return items


def crop_formula_image(
    page: fitz.Page, bbox: fitz.Rect, name: str, answer: Optional[str] = None
) -> str:
    FORMULA_DIR.mkdir(parents=True, exist_ok=True)
    rel = f"formulas/{name}.png"
    clip = (bbox + CROP_PAD) & page.rect
    if answer and answer != "?":
        clip = shrink_bbox_before_answer(page, clip, answer)

    hits = find_answer_hits(page, answer, clip) if answer and answer != "?" else []
    if hits:
        src = fitz.open()
        src.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
        wp = src[0]
        for h in hits:
            r = (h + (-3, -2, 3, 2)) & clip
            if r.width > 1 and r.height > 1:
                wp.add_redact_annot(r, fill=(1, 1, 1))
        wp.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
        pix = wp.get_pixmap(matrix=CROP_MATRIX, clip=clip, alpha=False)
        src.close()
    else:
        pix = page.get_pixmap(matrix=CROP_MATRIX, clip=clip, alpha=False)
    pix.save(str(FORMULA_DIR / f"{name}.png"))
    return rel


def region_bbox(page: fitz.Page, lines: List[dict], y0: float, y1: float) -> fitz.Rect:
    """合并纵坐标范围内的行，并使用 PDF 内容区全宽，保证题干/公式完整可见。"""
    in_range = [ln for ln in lines if y0 - 1 <= ln["top"] <= y1 + 1]
    content_x1 = page.rect.width - CONTENT_MARGIN
    if not in_range:
        return fitz.Rect(CONTENT_MARGIN, y0, content_x1, y1 + 18)
    rects = [line_bbox(ln, page.rect) for ln in in_range]
    merged = merge_bbox(rects)
    x0 = max(0, min(merged.x0, CONTENT_MARGIN) - 4)
    x1 = min(page.rect.width, max(merged.x1, content_x1) + 4)
    ty0 = max(0, merged.y0 - 4)
    ty1 = min(page.rect.height, merged.y1 + 6)
    if ty1 - ty0 < 16:
        ty1 = ty0 + 18
    return fitz.Rect(x0, ty0, x1, ty1)


def find_next_question_top(page: fitz.Page, lines: List[dict], qid: int) -> float:
    if qid >= 100:
        return page.rect.height
    for pat in (f"{qid + 1}.", f"{qid + 1}．"):
        hits = page.search_for(pat)
        if hits:
            return min(h.y0 for h in hits)
    for ln in lines:
        if re.match(rf"^\s*{qid + 1}\s*[\．\.]", ln["text"]):
            return ln["top"]
    return page.rect.height


def find_question_start_top(lines: List[dict], qid: int) -> Optional[float]:
    for ln in lines:
        if re.match(rf"^\s*{qid}(?:\s*[\．\.]\s*|\s+(?=[\u4e00-\u9fff]))", ln["text"]):
            return ln["top"]
    return None


def find_option_markers_for_question(
    page: fitz.Page, lines: List[dict], qid: int, stem_y0: float
) -> Dict[str, fitz.Rect]:
    """用 PDF 搜索定位本题 A/B/C/D 标记（支持两行两列布局）。"""
    next_y = find_next_question_top(page, lines, qid)
    candidates: Dict[str, List[fitz.Rect]] = {lab: [] for lab in "ABCD"}
    y_min = stem_y0 + 4
    for label in "ABCD":
        for pat in (f"{label}.", f"{label}．", f"{label}、"):
            for hit in page.search_for(pat):
                if y_min <= hit.y0 < next_y - 2:
                    candidates[label].append(hit)
            if candidates[label]:
                break

    markers: Dict[str, fitz.Rect] = {}
    for label, hits in candidates.items():
        if hits:
            markers[label] = min(hits, key=lambda h: h.y0)
    return markers


def find_question_y_range(page: fitz.Page, lines: List[dict], qid: int, block: str) -> Tuple[float, float]:
    """定位题干纵坐标：从题号行到选项区之前。"""
    start_top = find_question_start_top(lines, qid)
    if start_top is None:
        return 0, page_max(lines)

    markers = find_option_markers_for_question(page, lines, qid, start_top)
    if len(markers) >= 2:
        first_opt = min(m.y0 for m in markers.values())
        end = first_opt - 4
    else:
        end = start_top + 100
        for ln in lines:
            if ln["top"] <= start_top:
                continue
            if OPTION_MARKER_FIND.search(ln["text"]):
                end = ln["top"] - 2
                break
            if re.match(rf"^\s*{qid + 1}\s*[\．\.]", ln["text"]):
                end = ln["top"] - 2
                break

    stem_lines = [ln for ln in lines if start_top <= ln["top"] < end]
    if stem_lines:
        last = max(stem_lines, key=lambda x: x["top"])
        end = max(end, last["top"] + max(last.get("size", 12) * 1.5, 18))
        if markers:
            end = min(end, min(m.y0 for m in markers.values()) - 2)
    return start_top, end


def find_options_block_y_range(
    page: fitz.Page, lines: List[dict], qid: int, stem_y0: float
) -> Tuple[float, float]:
    """定位选项区纵坐标范围。"""
    next_y = find_next_question_top(page, lines, qid)
    markers = find_option_markers_for_question(page, lines, qid, stem_y0)
    if markers:
        return min(m.y0 for m in markers.values()) - 4, next_y - 2

    opt_start = stem_y0 + 4
    opt_end = next_y - 2
    for ln in lines:
        if ln["top"] < stem_y0:
            continue
        if OPTION_MARKER_FIND.search(ln["text"]) and opt_start > stem_y0 + 4:
            opt_start = min(opt_start, ln["top"])
        elif OPTION_MARKER_FIND.search(ln["text"]):
            opt_start = ln["top"]
    return opt_start, opt_end


def compute_option_bbox(
    page: fitz.Page, label: str, markers: Dict[str, fitz.Rect]
) -> Optional[fitz.Rect]:
    """按 PDF 实际文字边界收紧选项截图，避免带入相邻选项。"""
    if label not in markers:
        return None
    hit = markers[label]
    order = list("ABCD")
    idx = order.index(label)

    x0_lim = hit.x0
    x1_lim = page.rect.width - CONTENT_MARGIN
    y0_lim = hit.y0 - 2
    y1_lim = hit.y1 + 48

    for next_lab in order[idx + 1 :]:
        if next_lab in markers:
            nr = markers[next_lab]
            if abs(nr.y0 - hit.y0) < 14:
                x1_lim = nr.x0 - 4
                break

    for prev_lab in order[:idx]:
        if prev_lab in markers:
            pr = markers[prev_lab]
            if abs(pr.y0 - hit.y0) < 14:
                x0_lim = max(x0_lim, pr.x1)

    below = [
        m
        for lab, m in markers.items()
        if lab != label and m.y0 > hit.y0 + 6 and abs(m.x0 - hit.x0) < 55
    ]
    if below:
        y1_lim = min(y1_lim, min(m.y0 for m in below) - 3)

    region = fitz.Rect(x0_lim - 6, y0_lim - 6, x1_lim + 6, y1_lim + 6)
    label_pats = (f"{label}.", f"{label}．", f"{label}、")
    content_rects: List[fitz.Rect] = []

    for text, sb in iter_span_rects(page):
        if not region.intersects(sb):
            continue
        stripped = text.strip()
        if any(stripped.startswith(p) for p in label_pats) and sb.x0 <= hit.x1 + 6:
            content_rects.append(sb)
            continue
        if (
            sb.x0 >= hit.x0 - 3
            and sb.y0 >= hit.y0 - 4
            and sb.x1 <= x1_lim + 6
            and sb.y0 < y1_lim + 2
        ):
            content_rects.append(sb)

    if not content_rects:
        return fitz.Rect(
            max(CONTENT_MARGIN, hit.x0 - 4),
            hit.y0 - 4,
            x1_lim,
            min(y1_lim, hit.y1 + 26),
        )

    merged = merge_bbox(content_rects)
    return fitz.Rect(
        max(CONTENT_MARGIN, merged.x0 - 3),
        merged.y0 - 3,
        min(x1_lim, merged.x1 + 4),
        merged.y1 + 4,
    )


def crop_option_on_page(
    page: fitz.Page,
    label: str,
    markers: Dict[str, fitz.Rect],
    y_max: float,
    name: str,
) -> Optional[str]:
    bbox = compute_option_bbox(page, label, markers)
    if not bbox or bbox.width < 8 or bbox.height < 6:
        return None
    return crop_formula_image(page, bbox, name)


def page_max(lines: List[dict]) -> float:
    return max((ln["top"] for ln in lines), default=9999)


def is_math_line(ln: dict) -> bool:
    text = ln.get("text", "")
    if re.match(rf"^\s*\d+[\．\.]", text):
        return False
    if ln.get("math") and ln.get("left", 0) > 120:
        return True
    if not re.search(r"[\u4e00-\u9fff]{2,}", text) and re.search(r"[=+\-*/\(\)sSGH\d]", text):
        return True
    return False


def line_display_text(ln: dict, strip_qid: bool = False) -> str:
    text = ln.get("text", "")
    if strip_qid:
        text = QUESTION_HEAD_RE.sub("", text, count=1).strip()
    return text_to_display(text)


def find_math_lines_in_range(lines: List[dict], y0: float, y1: float) -> List[dict]:
    return [ln for ln in lines if y0 <= ln["top"] <= y1 and is_math_line(ln)]


def crop_stem_formula_image(
    page: fitz.Page,
    lines: List[dict],
    y0: float,
    y1: float,
    qid: int,
    idx: int,
    answer: Optional[str] = None,
) -> Optional[str]:
    math_lines = find_math_lines_in_range(lines, y0, y1)
    if not math_lines:
        return None
    ty0 = min(ln["top"] for ln in math_lines)
    ty1 = max(ln["top"] + max(ln.get("size", 12) * 1.5, 18) for ln in math_lines)
    bbox = region_bbox(page, lines, ty0, ty1)
    return crop_formula_image(page, bbox, f"q{qid}_f_{idx}", answer=answer)


def extract_formula_segments(
    page: fitz.Page,
    lines: List[dict],
    stem: str,
    qid: int,
    counter: List[int],
    block: str,
    answer: Optional[str] = None,
) -> Tuple[List[dict], Optional[str]]:
    """题干：纯文字用文本；含公式/图形时按行混排文字与公式截图。"""
    head = QUESTION_HEAD_RE.sub("", stem, count=1).strip()
    head, answer_from_head = extract_answer(head)
    stem_answer = answer_from_head or answer

    y0, y1 = find_question_y_range(page, lines, qid, block)
    stem_lines = sorted(
        [ln for ln in lines if y0 - 1 <= ln["top"] <= y1 + 1],
        key=lambda x: x["top"],
    )

    if not stem_needs_formula_image(head, stem_lines):
        return [{"type": "text", "content": text_to_display(head)}], answer_from_head

    segments: List[dict] = []
    text_buf: List[str] = []

    def flush_text() -> None:
        if not text_buf:
            return
        merged = text_to_display(" ".join(text_buf))
        if merged.strip():
            segments.append({"type": "text", "content": merged})
        text_buf.clear()

    i = 0
    while i < len(stem_lines):
        ln = stem_lines[i]
        if is_math_line(ln):
            flush_text()
            j = i + 1
            while j < len(stem_lines) and is_math_line(stem_lines[j]):
                j += 1
            ty0 = stem_lines[i]["top"]
            ty1 = stem_lines[j - 1]["top"] + max(stem_lines[j - 1].get("size", 12) * 1.5, 18)
            counter[0] += 1
            rel = crop_stem_formula_image(
                page, lines, ty0, ty1, qid, counter[0], answer=stem_answer
            )
            if rel:
                segments.append({"type": "image", "src": rel, "alt": "公式"})
            i = j
        else:
            text_buf.append(line_display_text(ln, strip_qid=(i == 0)))
            i += 1

    flush_text()
    if not segments:
        segments.append({"type": "text", "content": text_to_display(head)})
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

    FORMULA_DIR.mkdir(parents=True, exist_ok=True)
    for old in FORMULA_DIR.glob("*.png"):
        old.unlink()

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

        segments, ans2 = extract_formula_segments(
            page, lines, stem, qid, img_counter, block, answer=answer
        )
        if not answer:
            answer = ans2

        y0, y1 = find_question_y_range(page, lines, qid, block)
        opt_y0, opt_y1 = find_options_block_y_range(page, lines, qid, y0)
        markers = find_option_markers_for_question(page, lines, qid, y0)
        options = {}
        for label, val in raw_opts.items():
            options[label] = build_option_segments(
                val, qid, label, img_counter, page, markers, opt_y1
            )

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
