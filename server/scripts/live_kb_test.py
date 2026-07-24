"""线上知识库体系验证:docx 上传 + 引用范围隔离(经 HTTPS)。"""
import json
import re
from pathlib import Path

import httpx

BASE = "https://edu-demo.openneo.ai"
TOK = "6kPv6zjyaen6TD80_IvScg"
H = {"Authorization": f"Bearer {TOK}"}
DOC = Path(__file__).resolve().parents[2] / "doc" / "统一赛题.docx"

kbs = httpx.get(BASE + "/api/portal/kbs", headers=H, timeout=30).json()
print("KBS:", [(k["code"], k["name"], k["material_code"], k["docs"]) for k in kbs])
kbc = next(k for k in kbs if k["code"] == "kb-c")

data = DOC.read_bytes()
r = httpx.post(BASE + "/api/portal/documents", headers=H, timeout=600,
               files={"file": ("统一赛题.docx", data)},
               data={"kb_id": str(kbc["id"]), "title": "统一赛题"})
j = r.json()
print("upload:", r.status_code, "| chunks=", (j.get("stats") or {}).get("chunks"),
      "| entities=", ((j.get("stats") or {}).get("extract") or {}).get("entities"))


def chat(role: str, text: str) -> str:
    s = httpx.post(BASE + "/api/session", json={"role": role}, timeout=30).json()["session_id"]
    reply = ""
    with httpx.stream("POST", BASE + "/api/chat",
                      json={"session_id": s, "text": text}, timeout=180) as resp:
        for line in resp.iter_lines():
            if line.startswith("data:"):
                try:
                    p = json.loads(line[5:].strip())
                except Exception:
                    continue
                reply += p.get("text", "")
    return reply


r1 = chat("student", "大赛的提交时限是多久?")
print("student scope:", re.sub(r"\s+", " ", r1)[:100])
r2 = chat("platform", "大赛的提交时限是多久?")
print("platform scope:", re.sub(r"\s+", " ", r2)[:140])
