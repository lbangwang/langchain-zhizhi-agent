"""API 路由包（在 MYSQL_ENABLED 时由 main 挂到 /api）。

技术点：APIRouter 按业务拆文件；一律 JWT（auth 的 register/login 除外）。
"""
