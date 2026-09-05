---
id: report-writer
name: 报告写作与落盘
triggers: [报告, 纪要, 攻略, PDF, 导出, docx, Word]
summary: 结构化写作并调用 create_pdf_report / write_text_file / create_doc_report 落盘
priority: 10
---

# report-writer

报告 / 纪要 / 攻略类写作与落盘。

流程建议：
1. 必要时先 `search_web` 补全事实
2. 整理结构化正文
3. 调用 `create_pdf_report`、`create_doc_report` 或 `write_text_file` 产出可下载产物
4. 回复中写明产物文件名与下载入口（右侧「产物」）

危险工具（写文件 / 生成 PDF / Word）受 HITL 管控，执行前可能需用户批准；搜索类工具无需确认。
