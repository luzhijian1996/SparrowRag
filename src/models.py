"""
MinerU 文档解析服务数据模型

定义 API 请求参数与响应结构，提供类型安全的接口调用。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class TaskState(str, Enum):
    """任务状态枚举"""
    WAITING_FILE = "waiting-file"   # 等待文件上传
    UPLOADING = "uploading"         # 文件下载/上传中
    PENDING = "pending"             # 排队中
    RUNNING = "running"             # 解析中
    CONVERTING = "converting"       # 格式转换中
    DONE = "done"                   # 完成
    FAILED = "failed"               # 失败


class ModelVersion(str, Enum):
    """模型版本枚举"""
    PIPELINE = "pipeline"
    VLM = "vlm"
    MINERU_HTML = "MinerU-HTML"


# ========================
# 精准解析 API 模型
# ========================

@dataclass
class PrecisionExtractRequest:
    """精准解析 - 单文件 URL 解析请求"""
    url: str
    model_version: str = "vlm"
    is_ocr: bool = False
    enable_formula: bool = True
    enable_table: bool = True
    language: str = "ch"
    data_id: Optional[str] = None
    callback: Optional[str] = None
    seed: Optional[str] = None
    extra_formats: Optional[List[str]] = None
    page_ranges: Optional[str] = None
    no_cache: bool = False
    cache_tolerance: int = 900

    def to_dict(self) -> dict:
        """转换为 API 请求体字典，过滤掉 None 值"""
        data = {
            "url": self.url,
            "model_version": self.model_version,
            "is_ocr": self.is_ocr,
            "enable_formula": self.enable_formula,
            "enable_table": self.enable_table,
            "language": self.language,
            "no_cache": self.no_cache,
            "cache_tolerance": self.cache_tolerance,
        }
        if self.data_id is not None:
            data["data_id"] = self.data_id
        if self.callback is not None:
            data["callback"] = self.callback
        if self.seed is not None:
            data["seed"] = self.seed
        if self.extra_formats is not None:
            data["extra_formats"] = self.extra_formats
        if self.page_ranges is not None:
            data["page_ranges"] = self.page_ranges
        return data


@dataclass
class PrecisionBatchFileItem:
    """精准解析 - 批量文件项（URL 方式）"""
    url: str
    data_id: Optional[str] = None
    is_ocr: Optional[bool] = None
    page_ranges: Optional[str] = None

    def to_dict(self) -> dict:
        data = {"url": self.url}
        if self.data_id is not None:
            data["data_id"] = self.data_id
        if self.is_ocr is not None:
            data["is_ocr"] = self.is_ocr
        if self.page_ranges is not None:
            data["page_ranges"] = self.page_ranges
        return data


@dataclass
class PrecisionBatchUploadFileItem:
    """精准解析 - 批量文件项（本地文件上传方式）"""
    name: str
    data_id: Optional[str] = None
    is_ocr: Optional[bool] = None
    page_ranges: Optional[str] = None

    def to_dict(self) -> dict:
        data = {"name": self.name}
        if self.data_id is not None:
            data["data_id"] = self.data_id
        if self.is_ocr is not None:
            data["is_ocr"] = self.is_ocr
        if self.page_ranges is not None:
            data["page_ranges"] = self.page_ranges
        return data


@dataclass
class PrecisionBatchExtractRequest:
    """精准解析 - 批量 URL 解析请求"""
    files: List[PrecisionBatchFileItem]
    model_version: str = "vlm"
    enable_formula: bool = True
    enable_table: bool = True
    language: str = "ch"
    callback: Optional[str] = None
    seed: Optional[str] = None
    extra_formats: Optional[List[str]] = None
    no_cache: bool = False
    cache_tolerance: int = 900

    def to_dict(self) -> dict:
        data = {
            "files": [f.to_dict() for f in self.files],
            "model_version": self.model_version,
            "enable_formula": self.enable_formula,
            "enable_table": self.enable_table,
            "language": self.language,
            "no_cache": self.no_cache,
            "cache_tolerance": self.cache_tolerance,
        }
        if self.callback is not None:
            data["callback"] = self.callback
        if self.seed is not None:
            data["seed"] = self.seed
        if self.extra_formats is not None:
            data["extra_formats"] = self.extra_formats
        return data


@dataclass
class PrecisionBatchUploadRequest:
    """精准解析 - 批量本地文件上传请求"""
    files: List[PrecisionBatchUploadFileItem]
    model_version: str = "vlm"
    enable_formula: bool = True
    enable_table: bool = True
    language: str = "ch"
    callback: Optional[str] = None
    seed: Optional[str] = None
    extra_formats: Optional[List[str]] = None

    def to_dict(self) -> dict:
        data = {
            "files": [f.to_dict() for f in self.files],
            "model_version": self.model_version,
            "enable_formula": self.enable_formula,
            "enable_table": self.enable_table,
            "language": self.language,
        }
        if self.callback is not None:
            data["callback"] = self.callback
        if self.seed is not None:
            data["seed"] = self.seed
        if self.extra_formats is not None:
            data["extra_formats"] = self.extra_formats
        return data


# ========================
# 响应模型
# ========================

@dataclass
class TaskResponse:
    """任务提交响应"""
    code: int
    msg: str
    trace_id: str
    task_id: str = ""
    # 批量模式额外返回
    batch_id: str = ""
    file_urls: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "TaskResponse":
        resp_data = data.get("data", {})
        return cls(
            code=data.get("code", -1),
            msg=data.get("msg", ""),
            trace_id=data.get("trace_id", ""),
            task_id=resp_data.get("task_id", ""),
            batch_id=resp_data.get("batch_id", ""),
            file_urls=resp_data.get("file_urls", []),
        )


@dataclass
class ExtractProgress:
    """解析进度"""
    extracted_pages: int = 0
    total_pages: int = 0
    start_time: str = ""


@dataclass
class TaskResult:
    """任务查询结果"""
    task_id: str = ""
    state: str = ""
    err_msg: str = ""
    err_code: int = 0
    # 精准解析 API 返回
    full_zip_url: str = ""
    data_id: str = ""
    extract_progress: Optional[ExtractProgress] = None
    # 批量结果中的文件名
    file_name: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "TaskResult":
        progress_data = data.get("extract_progress")
        progress = None
        if progress_data:
            progress = ExtractProgress(
                extracted_pages=progress_data.get("extracted_pages", 0),
                total_pages=progress_data.get("total_pages", 0),
                start_time=progress_data.get("start_time", ""),
            )
        return cls(
            task_id=data.get("task_id", ""),
            state=data.get("state", ""),
            err_msg=data.get("err_msg", ""),
            err_code=data.get("err_code", 0),
            full_zip_url=data.get("full_zip_url", ""),
            data_id=data.get("data_id", ""),
            extract_progress=progress,
            file_name=data.get("file_name", ""),
        )


@dataclass
class BatchResult:
    """批量任务查询结果"""
    batch_id: str = ""
    extract_results: List[TaskResult] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "BatchResult":
        results = [
            TaskResult.from_dict(item)
            for item in data.get("extract_result", [])
        ]
        return cls(
            batch_id=data.get("batch_id", ""),
            extract_results=results,
        )
