"""应用层端到端冒烟：注册→登录→SSE 问答（落库）→埋点→B 端筛选与三类维护操作→权限校验。

前置：已运行 scripts/init_db.py；.env 中 LLM 可用（会真实调用一次问答）。
用法: uv run python scripts/app_smoke_test.py
"""

from __future__ import annotations

import json
import sys
import time

from fastapi.testclient import TestClient

from rag_agent.api.main import app


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    c = TestClient(app)
    ok = True

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        mark = "✓" if cond else "✗"
        if not cond:
            ok = False
        print(f"{mark} {name}" + (f"  {detail}" if detail else ""))

    # ── 1. 健康检查 ───────────────────────────────────────────────
    h = c.get("/api/health").json()
    check("health 配置齐全", all((h["llm_configured"], h["embedding_configured"], h["auth_configured"])), str(h))

    # ── 2. 注册 / 登录 ────────────────────────────────────────────
    username = f"zs{int(time.time())}"
    r = c.post("/api/auth/register", json={
        "username": username, "password": "test123456",
        "user_type": "自然人", "display_name": "张工",
    })
    check("注册", r.status_code == 200, r.text[:120] if r.status_code != 200 else f"user={r.json()['user']}")
    token = r.json()["access_token"]
    H = {"Authorization": f"Bearer {token}"}

    r = c.post("/api/auth/login", json={"username": username, "password": "test123456"})
    check("登录", r.status_code == 200)
    r = c.post("/api/auth/login", json={"username": username, "password": "wrong"})
    check("错误密码被拒(401)", r.status_code == 401)
    r = c.post("/api/auth/register", json={"username": username, "password": "test123456"})
    check("重复用户名被拒(400)", r.status_code == 400)

    ra = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    check("管理员登录", ra.status_code == 200)
    AH = {"Authorization": f"Bearer {ra.json()['access_token']}"}

    # ── 3. 权限边界 ───────────────────────────────────────────────
    r = c.post("/api/chat", json={"question": "测试"})
    check("未登录提问被拒(401)", r.status_code == 401)
    r = c.get("/api/admin/qa", headers=H)
    check("普通用户访问后台被拒(403)", r.status_code == 403)

    # ── 4. C 端 SSE 问答（真实 LLM）───────────────────────────────
    events: list[dict] = []
    with c.stream("POST", "/api/chat", json={"question": "供应商提出质疑的时限是多少天？"}, headers=H) as resp:
        check("问答接口 200 + SSE", resp.status_code == 200 and "text/event-stream" in resp.headers["content-type"])
        qa_id = None
        answer = []
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            events.append(ev)
            if ev["type"] == "meta":
                qa_id = ev["qa_id"]
            elif ev["type"] == "delta":
                answer.append(ev["text"])
    types = [e["type"] for e in events]
    full_answer = "".join(answer)
    check("SSE 事件含 meta/delta/sources/done", all(t in types for t in ("meta", "delta", "sources", "done")), str(types))
    check("回答含'工作日'", "工作日" in full_answer, f"answer[:60]={full_answer[:60]!r}")

    # ── 5. 埋点（PRD 口径）────────────────────────────────────────
    r = c.post("/api/track", headers=H, json={
        "event_name": '"发送"按钮', "prop_name": "页面点击", "prop_value": "次数",
        "session_id": "s-smoke", "page": "/chat",
    })
    check("埋点上报", r.status_code == 200)
    r = c.post("/api/track", headers=H, json={"event_name": "登录", "prop_name": "页面点击", "prop_value": "次数"})
    check("非 PRD 口径埋点被拒(422)", r.status_code == 422)

    # ── 6. B 端列表与筛选 ─────────────────────────────────────────
    r = c.get("/api/admin/qa", params={"maintain_status": "未维护"}, headers=AH)
    body = r.json()
    check("后台列表(未维护)含新记录", r.status_code == 200 and body["total"] >= 1
          and any(it["id"] == qa_id for it in body["items"]), f"total={body['total']}")
    r = c.get("/api/admin/qa", params={"keyword": "质疑的时限"}, headers=AH)
    check("关键词筛选命中", any(it["id"] == qa_id for it in r.json()["items"]))
    r = c.get("/api/admin/qa", params={"username": username}, headers=AH)
    check("用户名筛选命中", r.json()["total"] >= 1)
    r = c.get("/api/admin/qa", params={"user_type": "自然人", "date_from": "2000-01-01", "page_size": 5}, headers=AH)
    check("角色+时间筛选+分页", r.status_code == 200 and len(r.json()["items"]) <= 5)

    # ── 7. 三类维护操作（状态机 + 修改时间刷新）────────────────────
    r = c.get("/api/admin/qa", params={"keyword": "质疑的时限"}, headers=AH)
    item = next(it for it in r.json()["items"] if it["id"] == qa_id)
    updated_before = item["updated_at"]
    time.sleep(1.1)  # DATETIME 为秒级精度，同秒内操作无法体现刷新

    r = c.post(f"/api/admin/qa/{qa_id}/mark-correct", headers=AH)
    check("标记正确→已维护", r.status_code == 200 and r.json()["maintain_status"] == "已维护")

    r = c.put(f"/api/admin/qa/{qa_id}", headers=AH, json={"answer": "人工修正后的回答：供应商应在知道或应知权益受损之日起七个工作日内提出质疑。"})
    check("编辑回答→已维护", r.status_code == 200 and r.json()["maintain_status"] == "已维护")
    r = c.get("/api/admin/qa", params={"keyword": "质疑的时限"}, headers=AH)
    it2 = next(it for it in r.json()["items"] if it["id"] == qa_id)
    check("修改时间已刷新", it2["updated_at"] > updated_before, f"{updated_before} → {it2['updated_at']}")

    r = c.post(f"/api/admin/qa/{qa_id}/no-need", headers=AH)
    check("不需要维护", r.status_code == 200 and r.json()["maintain_status"] == "不需要维护")

    r = c.post(f"/api/admin/qa/999999/mark-correct", headers=AH)
    check("不存在记录(404)", r.status_code == 404)

    print("\n" + ("全部通过 ✅" if ok else "存在失败项 ❌"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
