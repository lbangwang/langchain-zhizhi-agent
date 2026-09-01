-- W2: 知识库文档元数据 + 工具审计 + 产物

CREATE TABLE IF NOT EXISTS kb_document (
    id              CHAR(32)     NOT NULL PRIMARY KEY COMMENT '文档ID',
    user_id         CHAR(32)     NOT NULL COMMENT '归属用户',
    filename        VARCHAR(256) NOT NULL,
    content_type    VARCHAR(128) NULL,
    char_count      INT          NOT NULL DEFAULT 0,
    chunk_count     INT          NOT NULL DEFAULT 0,
    status          INT          NOT NULL DEFAULT 1 COMMENT '1=可用 0=禁用',
    create_date     DATETIME     NOT NULL,
    create_by       VARCHAR(64)  NULL,
    update_date     DATETIME     NOT NULL,
    update_by       VARCHAR(64)  NULL,
    is_del          TINYINT      NOT NULL DEFAULT 0,
    KEY idx_kb_document_user_id (user_id),
    KEY idx_kb_document_is_del (is_del)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库文档';

CREATE TABLE IF NOT EXISTS tool_audit (
    id              CHAR(32)     NOT NULL PRIMARY KEY,
    user_id         CHAR(32)     NOT NULL,
    chat_id         CHAR(32)     NULL,
    tool_name       VARCHAR(64)  NOT NULL,
    input_preview   VARCHAR(512) NULL,
    output_preview  VARCHAR(1024) NULL,
    status          VARCHAR(32)  NOT NULL DEFAULT 'ok',
    create_date     DATETIME     NOT NULL,
    KEY idx_tool_audit_user_id (user_id),
    KEY idx_tool_audit_chat_id (chat_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='工具调用审计';

CREATE TABLE IF NOT EXISTS artifact (
    id              CHAR(32)     NOT NULL PRIMARY KEY,
    user_id         CHAR(32)     NOT NULL,
    chat_id         CHAR(32)     NULL,
    filename        VARCHAR(256) NOT NULL,
    content_type    VARCHAR(128) NULL,
    storage_path    VARCHAR(512) NOT NULL,
    byte_size       INT          NOT NULL DEFAULT 0,
    create_date     DATETIME     NOT NULL,
    is_del          TINYINT      NOT NULL DEFAULT 0,
    KEY idx_artifact_user_id (user_id),
    KEY idx_artifact_chat_id (chat_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Agent 产物';
