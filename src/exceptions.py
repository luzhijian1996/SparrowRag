"""
MinerU 文档解析服务自定义异常

提供结构化的异常体系，便于调用方精确捕获和处理不同类型的错误。
"""


class MinerUError(Exception):
    """MinerU 服务异常基类"""

    def __init__(self, message: str, code: int = 0, trace_id: str = ""):
        self.message = message
        self.code = code
        self.trace_id = trace_id
        super().__init__(message)

    def __str__(self) -> str:
        parts = [f"code={self.code}", f"msg={self.message}"]
        if self.trace_id:
            parts.append(f"trace_id={self.trace_id}")
        return f"MinerUError({', '.join(parts)})"


class MinerUApiError(MinerUError):
    """API 接口返回业务错误（code != 0）"""
    pass


class MinerUTaskFailedError(MinerUError):
    """解析任务执行失败（state=failed）"""

    def __init__(self, message: str, task_id: str = "", code: int = 0, trace_id: str = ""):
        self.task_id = task_id
        super().__init__(message, code=code, trace_id=trace_id)

    def __str__(self) -> str:
        parts = [f"task_id={self.task_id}", f"code={self.code}", f"msg={self.message}"]
        if self.trace_id:
            parts.append(f"trace_id={self.trace_id}")
        return f"MinerUTaskFailedError({', '.join(parts)})"


class MinerUTimeoutError(MinerUError):
    """轮询超时，任务未在限定时间内完成"""

    def __init__(self, task_id: str, timeout: int):
        self.task_id = task_id
        self.timeout = timeout
        super().__init__(f"任务轮询超时（{timeout}s），task_id={task_id}")


class MinerUUploadError(MinerUError):
    """文件上传失败"""
    pass


class MinerUConfigError(MinerUError):
    """配置错误（如 Token 未设置）"""
    pass
