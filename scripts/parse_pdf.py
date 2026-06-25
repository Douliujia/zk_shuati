#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 PDF 解析选择题，题干/公式以 PDF 原图截图为主，保证与源文档一致。"""

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
    markers: Dict[str, fitz.Rect],
    opt_y1: float,
) -> List[dict]:
    val = val.strip()
    formula_like = bool(
        re.search(r"[=+]|s\s*s|s\)|\(\s*1\)|G\(|H\(|\\", val)
        or any("\uf000" <= ch <= "\uf0ff" for ch in val)
    ) and len(re.findall(r"[\u4e00-\u9fff]", val)) < 4
    has_marker = label in markers
    # 纯中文选项保留文字；PDF 上能定位到标记或含公式的选项用原图
    if not has_marker and re.search(r"[\u4e00-\u9fff]", val) and not formula_like:
        return [{"type": "text", "content": val}]

    img_counter[0] += 1
    rel = crop_option_on_page(
        page, label, markers, opt_y1, f"q{qid}_opt_{label}_{img_counter[0]}"
    )
    if rel:
        return [{"type": "image", "src": rel, "alt": f"选项{label}"}]
    return [{"type": "text", "content": val}]


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


def crop_formula_image(page: fitz.Page, bbox: fitz.Rect, name: str) -> str:
    FORMULA_DIR.mkdir(parents=True, exist_ok=True)
    rel = f"formulas/{name}.png"
    clip = (bbox + CROP_PAD) & page.rect
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


def crop_option_on_page(
    page: fitz.Page,
    label: str,
    markers: Dict[str, fitz.Rect],
    y_max: float,
    name: str,
) -> Optional[str]:
    """按 PDF 原样截取单个选项（含公式）。"""
    if label not in markers:
        return None
    hit = markers[label]
    order = ["A", "B", "C", "D"]
    idx = order.index(label)
    x0 = max(CONTENT_MARGIN, hit.x0 - 4)
    x1 = page.rect.width - CONTENT_MARGIN
    y0 = hit.y0 - 4
    y1 = hit.y1 + 26

    for next_lab in order[idx + 1:]:
        if next_lab not in markers:
            continue
        nr = markers[next_lab]
        if abs(nr.y0 - hit.y0) < 14:
            x1 = min(x1, nr.x0 - 4)
        else:
            y1 = min(y1, nr.y0 - 2)
            break

    below_col = [
        m
        for lab, m in markers.items()
        if lab != label and m.y0 > hit.y0 + 8 and abs(m.x0 - hit.x0) < 50
    ]
    if below_col:
        y1 = min(y1, min(m.y0 for m in below_col) - 2)

    bbox = fitz.Rect(x0, y0, x1, y1)
    if bbox.width < 10 or bbox.height < 8:
        return None
    return crop_formula_image(page, bbox, name)


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
    """题干一律从 PDF 截取整段原图，保证与源文档格式一致。"""
    head = QUESTION_HEAD_RE.sub("", stem, count=1).strip()
    _, answer_from_head = extract_answer(head)

    y0, y1 = find_question_y_range(page, lines, qid, block)
    counter[0] += 1
    bbox = region_bbox(page, lines, y0, y1)
    rel = crop_formula_image(page, bbox, f"q{qid}_stem_{counter[0]}")
    return [{"type": "image", "src": rel, "alt": f"第{qid}题"}], answer_from_head


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

        segments, ans2 = extract_formula_segments(page, lines, stem, qid, img_counter, block)
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
