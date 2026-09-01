# Agent Skill：可插拔能力说明（W3 D4）

## report-writer

报告 / 纪要 / 攻略类写作与落盘。触发词：报告、纪要、攻略、PDF、导出。

流程建议：
1. 必要时先 `search_web` 补全事实
2. 整理结构化正文
3. 调用 `create_pdf_report` 或 `write_text_file` 产出可下载产物
4. 回复中写明 artifact_id 与下载路径

危险工具（写文件 / 生成 PDF）受 HITL 管控，执行前可能需用户批准；搜索类工具无需确认。
