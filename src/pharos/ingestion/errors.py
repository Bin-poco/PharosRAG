"""摄取领域错误。"""


class UploadError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


_TRANSIENT_MINERU_CODES = {
    "mineru_unavailable", "mineru_upload_failed", "mineru_download_failed", "mineru_timeout",
}


def is_transient_ingestion_error(exc: Exception) -> bool:
    """只重试明确的基础设施瞬态错误；格式、权限和配置错误一律不重试。"""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "inference_unavailable", False):
            return True
        if getattr(current, "code", None) in _TRANSIENT_MINERU_CODES:
            return True
        if isinstance(current, (ConnectionError, TimeoutError)):
            return True
        module = type(current).__module__
        name = type(current).__name__
        if module.startswith("httpx"):
            if name != "HTTPStatusError":
                return True
            status_code = getattr(getattr(current, "response", None), "status_code", None)
            if status_code == 429 or (status_code is not None and int(status_code) >= 500):
                return True
        if module.startswith("qdrant_client"):
            status_code = getattr(current, "status_code", None)
            if status_code is None or int(status_code) >= 500:
                return True
        if module.startswith("sqlalchemy") and name in {
            "OperationalError", "InterfaceError", "DisconnectionError", "TimeoutError",
        }:
            return True
        current = current.__cause__ or current.__context__
    return False
