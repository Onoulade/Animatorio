class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "bad_request") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class NoAssetOpenError(ApiError):
    def __init__(self) -> None:
        super().__init__('No asset open — choose "Open" or "New from image" first.', 409, "no_asset_open")
