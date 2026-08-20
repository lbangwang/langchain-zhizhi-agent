from langchain_core.prompts import ChatPromptTemplate
class PromptLibrary:
    """可复用的提示词模板库"""
    TRANSLATOR = ChatPromptTemplate.from_messages([
    ("system", "你是专业翻译，精通{source_lang}和{target_lang}"),
    ("user", "翻译以下文本：\n{text}")
    ])
    CODE_REVIEWER = ChatPromptTemplate.from_messages([
    ("system", "你是{language}代码审查专家，重点关注{focus}"),
    ("user", "审查代码：\n```{language}\n{code}\n```")
    ])
    SUMMARIZER = ChatPromptTemplate.from_messages([
    ("system", "你是内容摘要专家"),
    ("user", "将以下内容总结为{num}个要点：\n{content}")
    ])
    TUTOR = ChatPromptTemplate.from_messages([
    ("system", "你是{subject}导师，学生水平：{level}"),
    ("user", "{question}")
])