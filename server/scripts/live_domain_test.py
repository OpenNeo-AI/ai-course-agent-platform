"""线上知识域体系验证:域列表 + agents.yaml 域语法 + 引用范围隔离。"""
import json
import re

import httpx

BASE = "https://edu-demo.openneo.ai"
TOK = "6kPv6zjyaen6TD80_IvScg"
H = {"Authorization": f"Bearer {TOK}"}

# 1) 更新远端 agents.yaml 为知识域语法
SCOPE = """# 智能体引用范围:每个入口对接列出的知识域,范围外内容不参与 RAG
student:
  identity: student
  domains: [domain-a]
teacher:
  identity: teacher
  domains: [domain-b]
platform:
  identity: org
  domains: [domain-c]
"""
r = httpx.put(BASE + "/api/portal/config/agents.yaml", headers=H,
              json={"content": SCOPE}, timeout=30)
print("agents.yaml PUT:", r.status_code)

# 2) 知识域列表
doms = httpx.get(BASE + "/api/portal/domains", headers=H, timeout=30).json()
print("DOMAINS:", [(d["code"], d["name"], d["kbs"], d["entities"], d["rules"]) for d in doms])
kbs = httpx.get(BASE + "/api/portal/kbs", headers=H, timeout=30).json()
print("KBS:", [(k["code"], k["name"], k["domain_name"], k["docs"]) for k in kbs])


# 3) 引用范围隔离
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
print("student:", re.sub(r"\s+", " ", r1)[:90])
r2 = chat("platform", "大赛的提交时限是多久?")
print("platform:", re.sub(r"\s+", " ", r2)[:130])
r3 = chat("student", "北京线下班多少钱?")
print("student in-scope:", re.sub(r"\s+", " ", r3)[:110])
