"""验证:三个 MCP 端点 + 作用域隔离 + agents 配置接口。"""
import json
import os

import httpx

BASE = os.environ.get("BASE", "https://edu-demo.openneo.ai")
TOK = os.environ.get("PORTAL_TOKEN", "6kPv6zjyaen6TD80_IvScg")   # portal 令牌
MCP_TOK = os.environ.get("MCP_TOKEN", "")                          # MCP 渠道令牌(系统设置签发)
H = {"Content-Type": "application/json",
     "Accept": "application/json, text/event-stream"}
if MCP_TOK:
    H["Authorization"] = f"Bearer {MCP_TOK}"


def mcp_call(endpoint: str, method: str, params: dict | None = None,
             sid: str = "", rid: int = 1):
    headers = dict(H)
    if sid:
        headers["Mcp-Session-Id"] = sid
    r = httpx.post(endpoint, headers=headers,
                   json={"jsonrpc": "2.0", "id": rid, "method": method,
                         "params": params or {}}, timeout=120)
    session = r.headers.get("mcp-session-id") or sid
    body = r.text
    data = None
    for line in body.splitlines():
        if line.startswith("data:"):
            try:
                data = json.loads(line[5:].strip())
            except Exception:
                pass
    if data is None and body.strip().startswith("{"):
        try:
            data = json.loads(body)
        except Exception:
            pass
    if data is None:
        data = {"_raw": body[:300], "_status": r.status_code}
    return r.status_code, session, data


def tool_result(data):
    try:
        return json.loads(data["result"]["content"][0]["text"])
    except Exception:
        return data


out = []
for name, path in (("platform", "/mcp"), ("student", "/mcp/student"), ("teacher", "/mcp/teacher")):
    ep = BASE + path
    st, sid, init = mcp_call(ep, "initialize", {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "verify", "version": "0"}})
    mcp_call(ep, "notifications/initialized", sid=sid)
    _, _, tl = mcp_call(ep, "tools/list", sid=sid, rid=2)
    if isinstance(tl, dict) and "result" in tl:
        tools = sorted(t["name"] for t in tl["result"].get("tools", []))
        has_material = any("material" in (t.get("inputSchema", {}).get("properties", {}))
                           for t in tl["result"].get("tools", []))
        out.append(f"[{name}] init={st} tools={tools} schema_has_material={has_material}")
    else:
        out.append(f"[{name}] init={st} UNPARSED: {tl}")

# 作用域隔离:student 端点问教师产品费用 → 域隔离(找不到该班型)
_, sid_s, _ = mcp_call(BASE + "/mcp/student", "initialize", {
    "protocolVersion": "2025-03-26", "capabilities": {},
    "clientInfo": {"name": "v", "version": "0"}})
_, _, r1 = mcp_call(BASE + "/mcp/student", "tools/call", {
    "name": "calculate_fee",
    "arguments": {"product_name": "L2暑期集训班",
                  "payment_date": "2026-07-10"}}, sid=sid_s, rid=3)
out.append("student×教师产品 fee → " + json.dumps(tool_result(r1), ensure_ascii=False)[:100])

# student 端点正常费用
_, _, r2 = mcp_call(BASE + "/mcp/student", "tools/call", {
    "name": "calculate_fee",
    "arguments": {"product_name": "北京线下班",
                  "payment_date": "2026-07-10", "group_count": 3}}, sid=sid_s, rid=4)
res2 = tool_result(r2)
out.append(f"student×北京线下班 fee → total={res2.get('total')} applied={res2.get('applied_which')}")

# teacher 端点推荐
_, sid_t, _ = mcp_call(BASE + "/mcp/teacher", "initialize", {
    "protocolVersion": "2025-03-26", "capabilities": {},
    "clientInfo": {"name": "v", "version": "0"}})
_, _, r3 = mcp_call(BASE + "/mcp/teacher", "tools/call", {
    "name": "recommend_products",
    "arguments": {"date_start": "2026-08-03", "date_end": "2026-08-05",
                  "days_off_continuous": True, "level": "L2",
                  "goal": "AI教学应用开发"}}, sid=sid_t, rid=5)
res3 = tool_result(r3)
names = [c["product"]["name"] for c in res3.get("candidates", [])]
out.append(f"teacher recommend → {names}")

# agents 配置接口
ag = httpx.get(BASE + "/api/portal/agents", headers={"Authorization": f"Bearer {TOK}"},
               timeout=30).json()
out.append("agents config → " + json.dumps(ag, ensure_ascii=False))

with open("data/mcp_verify.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("written data/mcp_verify.txt")
