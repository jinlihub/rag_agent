"""初始化应用层四张表（幂等）+ 播种管理员账号：

- user_account      用户（系统角色 admin/user；业务角色 企业用户/自然人）
- qa_record         问答记录（维护状态机：未维护 → 已维护 / 不需要维护）
- tracking_event    埋点事件（PRD：'发送'按钮 / 页面点击 / 次数）
- session_memory    会话滚动摘要（历史消息定期压缩的落点）

播种：admin / admin123（仅当不存在时创建）。
用法: uv run python scripts/init_db.py
"""

from __future__ import annotations

import sys

from rag_agent.security import hash_password
from rag_agent.store import create_user, get_user_by_username

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS user_account (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      username VARCHAR(64) NOT NULL UNIQUE COMMENT '登录名',
      password_hash VARCHAR(128) NOT NULL COMMENT 'pbkdf2: salt:hash',
      email VARCHAR(128) NULL,
      role VARCHAR(16) NOT NULL DEFAULT 'user' COMMENT '系统角色: admin/user',
      user_type VARCHAR(16) NOT NULL DEFAULT '自然人' COMMENT '业务角色: 管理员/企业用户/自然人',
      display_name VARCHAR(128) NULL COMMENT '展示名，如 XX公司 / 张工',
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统用户'
    """,
    """
    CREATE TABLE IF NOT EXISTS qa_record (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      session_id VARCHAR(36) NULL COMMENT '前端生成的会话 ID（C端对话历史聚合）',
      question TEXT NOT NULL COMMENT '用户问题',
      answer MEDIUMTEXT NULL COMMENT '智能回答（流式结束后回填）',
      answer_draft TEXT NULL COMMENT '未维护问题聚类草稿（同簇共用，cluster_unmaintained.py 写入）',
      sources TEXT NULL COMMENT '来源引用 JSON',
      maintain_status VARCHAR(16) NOT NULL DEFAULT '未维护' COMMENT '未维护/已维护/不需要维护',
      result_evaluation VARCHAR(16) NOT NULL DEFAULT '无' COMMENT '结果评价（枚举待产品定义 A11）',
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      INDEX idx_user (user_id),
      INDEX idx_session (user_id, session_id),
      INDEX idx_status (maintain_status),
      INDEX idx_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户问答记录（B端维护对象）'
    """,
    """
    CREATE TABLE IF NOT EXISTS tracking_event (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      event_name VARCHAR(64) NOT NULL COMMENT "事件名，如 '发送'按钮",
      prop_name VARCHAR(64) NOT NULL COMMENT '属性名，如 页面点击',
      prop_value VARCHAR(32) NOT NULL COMMENT '属性值，如 次数',
      user_id BIGINT NULL,
      session_id VARCHAR(64) NULL,
      page VARCHAR(64) NULL,
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_event (event_name),
      INDEX idx_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数据埋点事件'
    """,
    """
    CREATE TABLE IF NOT EXISTS session_memory (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      session_id VARCHAR(64) NOT NULL COMMENT '会话 ID（与 qa_record.session_id 同源）',
      user_id BIGINT NOT NULL,
      summary TEXT COMMENT '滚动压缩的对话要点摘要（实体清单/关键结论/纠正偏好）',
      upto_qa_id BIGINT NOT NULL DEFAULT 0 COMMENT '摘要已覆盖到的 qa_record.id',
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      UNIQUE KEY uk_session (session_id),
      INDEX idx_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='会话滚动摘要（历史消息定期压缩）'
    """,
]


def _ensure_session_column() -> None:
    """存量库迁移：qa_record 补 session_id 列与索引（幂等，已有则跳过）。"""
    from rag_agent.database import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) AS c FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'qa_record'
                  AND COLUMN_NAME = 'session_id'"""
        )
        if cur.fetchone()["c"]:
            print("· qa_record.session_id 已存在，跳过迁移")
            return
        cur.execute(
            "ALTER TABLE qa_record "
            "ADD COLUMN session_id VARCHAR(36) NULL COMMENT '前端生成的会话 ID（C端对话历史聚合）' AFTER user_id"
        )
        cur.execute("ALTER TABLE qa_record ADD INDEX idx_session (user_id, session_id)")
        conn.commit()
        print("✓ qa_record 迁移完成: 新增 session_id 列 + idx_session 索引")


def _ensure_answer_draft_column() -> None:
    """存量库迁移：qa_record 补 answer_draft 列（幂等，已有则跳过）。

    未维护问题聚类脚本把同簇共用的草稿写回此列；簇身份即「草稿内容相同」，不另建簇表。
    """
    from rag_agent.database import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) AS c FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'qa_record'
                  AND COLUMN_NAME = 'answer_draft'"""
        )
        if cur.fetchone()["c"]:
            print("· qa_record.answer_draft 已存在，跳过迁移")
            return
        cur.execute(
            "ALTER TABLE qa_record "
            "ADD COLUMN answer_draft TEXT NULL "
            "COMMENT '未维护问题聚类草稿（同簇共用，cluster_unmaintained.py 写入）' AFTER answer"
        )
        conn.commit()
        print("✓ qa_record 迁移完成: 新增 answer_draft 列")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    from rag_agent.database import get_conn

    for ddl in _DDL:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(ddl)
            conn.commit()
    print("✓ 四张应用表就绪: user_account / qa_record / tracking_event / session_memory")
    _ensure_session_column()
    _ensure_answer_draft_column()

    if get_user_by_username("admin") is None:
        create_user(
            username="admin",
            password_hash=hash_password("admin123"),
            user_type="管理员",
            display_name="管理员",
            role="admin",
        )
        print("✓ 已播种管理员: admin / admin123（仅测试环境用，上线前改密）")
    else:
        print("· 管理员已存在，跳过播种")


if __name__ == "__main__":
    main()
