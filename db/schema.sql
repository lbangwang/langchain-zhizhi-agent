-- W1 D2: 会话持久化表结构
-- 建库：
--   CREATE DATABASE IF NOT EXISTS zhizhi_ai_agent
--     DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
--
-- 业务 ID（id / chat_id / user_id / conversation_id）为 32 位字符串（UUID 去横线）。
-- 启用 MYSQL_ENABLED=true 前请先执行本脚本。

CREATE TABLE IF NOT EXISTS app_user (
    id              CHAR(32)     NOT NULL PRIMARY KEY COMMENT '主键，32位字符串',
    username        VARCHAR(64)  NOT NULL,
    password_hash   VARCHAR(255) NULL,
    nickname        VARCHAR(64)  NULL,
    status          INT          NOT NULL DEFAULT 1 COMMENT '1=正常 0=禁用',
    create_date     DATETIME     NOT NULL COMMENT '创建时间',
    create_by       VARCHAR(64)  NULL COMMENT '创建人',
    update_date     DATETIME     NOT NULL COMMENT '更新时间',
    update_by       VARCHAR(64)  NULL COMMENT '更新人',
    is_del          TINYINT      NOT NULL DEFAULT 0 COMMENT '0=未删除 1=已删除',
    enterprise_id   CHAR(32)     NULL COMMENT '企业/租户ID',
    UNIQUE KEY uk_app_user_username (username),
    KEY idx_app_user_enterprise_id (enterprise_id),
    KEY idx_app_user_is_del (is_del)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户';

CREATE TABLE IF NOT EXISTS conversation (
    id              CHAR(32)     NOT NULL PRIMARY KEY COMMENT '主键，32位字符串',
    chat_id         CHAR(32)     NOT NULL COMMENT '业务会话ID，对齐前端 chatId',
    user_id         CHAR(32)     NULL COMMENT '用户ID',
    agent_type      VARCHAR(32)  NOT NULL COMMENT '智能体类型',
    title           VARCHAR(128) NOT NULL,
    model           VARCHAR(64)  NULL,
    status          INT          NOT NULL DEFAULT 1 COMMENT '1=进行中 0=归档',
    create_date     DATETIME     NOT NULL COMMENT '创建时间',
    create_by       VARCHAR(64)  NULL COMMENT '创建人',
    update_date     DATETIME     NOT NULL COMMENT '更新时间',
    update_by       VARCHAR(64)  NULL COMMENT '更新人',
    is_del          TINYINT      NOT NULL DEFAULT 0 COMMENT '0=未删除 1=已删除',
    enterprise_id   CHAR(32)     NULL COMMENT '企业/租户ID',
    UNIQUE KEY uk_conversation_chat_id (chat_id),
    KEY idx_conversation_user_id (user_id),
    KEY idx_conversation_update_date (update_date),
    KEY idx_conversation_enterprise_id (enterprise_id),
    KEY idx_conversation_is_del (is_del)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='会话';

CREATE TABLE IF NOT EXISTS message (
    id                 CHAR(32)     NOT NULL PRIMARY KEY COMMENT '主键，32位字符串',
    conversation_id    CHAR(32)     NOT NULL COMMENT '会话主键ID',
    role               VARCHAR(32)  NOT NULL COMMENT 'user/assistant/system/tool',
    content            LONGTEXT     NOT NULL,
    metadata           LONGTEXT     NULL COMMENT '思考链/工具摘要等 JSON',
    create_date        DATETIME     NOT NULL COMMENT '创建时间',
    create_by          VARCHAR(64)  NULL COMMENT '创建人',
    update_date        DATETIME     NOT NULL COMMENT '更新时间',
    update_by          VARCHAR(64)  NULL COMMENT '更新人',
    is_del             TINYINT      NOT NULL DEFAULT 0 COMMENT '0=未删除 1=已删除',
    enterprise_id      CHAR(32)     NULL COMMENT '企业/租户ID',
    KEY idx_message_conversation_id (conversation_id),
    KEY idx_message_enterprise_id (enterprise_id),
    KEY idx_message_is_del (is_del)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='消息';


