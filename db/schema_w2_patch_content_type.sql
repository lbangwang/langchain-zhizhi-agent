-- 修复：docx MIME 过长导致入库失败
-- application/vnd.openxmlformats-officedocument.wordprocessingml.document ≈ 71 字符
ALTER TABLE kb_document
    MODIFY COLUMN content_type VARCHAR(128) NULL;
