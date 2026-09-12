"""文档与摄取任务的持久化模型和仓储。"""

from .repository import FileJobRepository, SQLJobRepository

__all__ = ["FileJobRepository", "SQLJobRepository"]
