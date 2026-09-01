-- W3: Trace 可观测

CREATE TABLE IF NOT EXISTS trace_span (
    id              CHAR(32)     NOT NULL PRIMARY KEY,
    trace_id        CHAR(32)     NOT NULL,
    parent_id       CHAR(32)     NULL,
    user_id         CHAR(32)     NOT NULL,
    chat_id         CHAR(32)     NULL,
    name            VARCHAR(128) NOT NULL,
    kind            VARCHAR(32)  NOT NULL DEFAULT 'root',
    status          VARCHAR(32)  NOT NULL DEFAULT 'ok',
    started_at      DATETIME     NOT NULL,
    ended_at        DATETIME     NULL,
    duration_ms     INT          NULL,
    meta_json       TEXT         NULL,
    KEY idx_trace_span_trace_id (trace_id),
    KEY idx_trace_span_user_id (user_id),
    KEY idx_trace_span_chat_id (chat_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='请求 Trace';
