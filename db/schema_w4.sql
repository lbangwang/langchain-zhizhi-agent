-- W4: 企业级 Agent 配置版本 + 审计扩展

CREATE TABLE IF NOT EXISTS agent_config (
    id              CHAR(32)     NOT NULL PRIMARY KEY,
    user_id         CHAR(32)     NOT NULL COMMENT '归属用户；空串表示系统默认种子需业务层处理',
    version         VARCHAR(32)  NOT NULL COMMENT '配置版本号，如 v1 / 2026.08.21.1',
    name            VARCHAR(128) NOT NULL DEFAULT 'default',
    system_prompt   TEXT         NULL,
    tools_json      TEXT         NULL COMMENT '工具白名单 JSON 数组',
    max_tool_calls  INT          NOT NULL DEFAULT 8,
    timeout_seconds INT          NOT NULL DEFAULT 180,
    hitl_enabled    TINYINT      NOT NULL DEFAULT 1,
    is_active       TINYINT      NOT NULL DEFAULT 1 COMMENT '1=当前生效',
    create_date     DATETIME     NOT NULL,
    update_date     DATETIME     NOT NULL,
    is_del          TINYINT      NOT NULL DEFAULT 0,
    UNIQUE KEY uk_agent_config_user_version (user_id, version),
    KEY idx_agent_config_user_active (user_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Agent 配置版本';

-- 工具审计补充配置版本（已有表则 ALTER；重复执行可能报错可忽略）
ALTER TABLE tool_audit
    ADD COLUMN config_version VARCHAR(32) NULL COMMENT '运行时绑定的配置版本' AFTER status;
