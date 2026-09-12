"""文档摄取流水线。"""

from .errors import UploadError
from .pipeline import IngestionPipeline

__all__ = ["IngestionPipeline", "UploadError"]
