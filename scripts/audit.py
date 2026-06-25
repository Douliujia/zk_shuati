#!/usr/bin/env python3
import json
import re
from pathlib import Path

data = json.loads(Path(__file__).parent.parent.joinpath("data/questions.json").read_text(encoding="utf-8"))

print("=== 选项不全 ===")
for q in data["questions"]:
    keys = set(q["options"].keys())
    if keys != {"A", "B", "C", "D"}:
        print(q["id"], sorted(keys), {k: q["options"][k] for k in q["options"]})

print("\n=== 选项内容过短/为空 ===")
for q in data["questions"]:
    for label, segs in q["options"].items():
        text = " ".join(s.get("content", "") for s in segs if s["type"] == "text")
        if len(text.strip()) <= 2 and not any(s["type"] == "image" for s in segs):
            print(q["id"], label, repr(text), segs)

print("\n=== 题干含 A/B 极点类 ===")
for q in data["questions"]:
    seg = " ".join(s.get("content", "") for s in q["segments"])
    if re.search(r"[AB][、，]?\s*[AB]", seg) or "极点A" in seg or "极点 B" in seg:
        print(q["id"], seg[:120])
        print("  opts:", {k: q["options"][k] for k in sorted(q["options"])})

print("\n=== 截图题 ===")
for q in data["questions"]:
    ni = sum(1 for s in q["segments"] if s["type"] == "image")
    no = sum(1 for v in q["options"].values() for s in v if s["type"] == "image")
    if ni or no:
        print(f"Q{q['id']}: stem={ni} opt={no}")
