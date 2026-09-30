"""
MinerU 文档解析服务配置模块

从项目根目录 .env 文件加载配置。
参考 .env.example 获取所有可配置项。
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _find_dotenv_path() -> Path:
    """
    查找 .env 文件路径。
    优先从项目根目录（src 的上一级）加载。
    """
    # 从当前文件位置推算项目根目录：src/config.py -> 根目录
    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / ".env"
    if env_path.is_file():
        return env_path
    # 兜底：从当前工作目录查找
    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        return cwd_env
    raise FileNotFoundError(
        f"未找到 .env 文件，请在项目根目录 {project_root} 下创建 .env 文件，"
        f"可参考 .env.example"
    )


def _load_dotenv(env_path: Optional[Path] = None) -> None:
    """
    加载 .env 文件到环境变量。
    依赖 python-dotenv，若未安装则抛出 ImportError。
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        raise ImportError(
            "需要安装 python-dotenv 来加载 .env 配置文件。"
            "请执行: pip install python-dotenv"
        )
    path = env_path or _find_dotenv_path()
    load_dotenv(dotenv_path=path, override=True)


@dataclass
class MinerUConfig:
    """MinerU API 配置，所有参数从 .env 文件加载"""

    # 基础配置
    base_url: str = "https://mineru.net"

    # 精准解析 API
    api_token: str = ""
    default_model_version: str = "vlm"

    # 解析默认参数
    is_ocr: bool = False
    enable_formula: bool = True
    enable_table: bool = True
    language: str = "ch"

    # 轮询配置
    poll_timeout: int = 300
    poll_interval: int = 3

    # 缓存配置
    no_cache: bool = False
    cache_tolerance: int = 900

    # 输出配置
    output_dir: str = "resources/parsed_output"

    # MinerU 限制
    max_pages_per_request: int = 200

    @classmethod
    def from_env(cls, env_path: Optional[str] = None) -> "MinerUConfig":
        """
        从 .env 文件加载配置，构建 MinerUConfig 实例。

        Args:
            env_path: .env 文件路径，为 None 时自动查找项目根目录下的 .env
        """
        path = Path(env_path) if env_path else None
        _load_dotenv(path)

        return cls(
            base_url=os.getenv("MINERU_BASE_URL", "https://mineru.net"),
            api_token=os.getenv("MINERU_API_TOKEN", ""),
            default_model_version=os.getenv("MINERU_DEFAULT_MODEL_VERSION", "vlm"),
            is_ocr=os.getenv("MINERU_IS_OCR", "false").lower() in ("true", "1", "yes"),
            enable_formula=os.getenv("MINERU_ENABLE_FORMULA", "true").lower() in ("true", "1", "yes"),
            enable_table=os.getenv("MINERU_ENABLE_TABLE", "true").lower() in ("true", "1", "yes"),
            language=os.getenv("MINERU_LANGUAGE", "ch"),
            poll_timeout=int(os.getenv("MINERU_POLL_TIMEOUT", "300")),
            poll_interval=int(os.getenv("MINERU_POLL_INTERVAL", "3")),
            no_cache=os.getenv("MINERU_NO_CACHE", "false").lower() in ("true", "1", "yes"),
            cache_tolerance=int(os.getenv("MINERU_CACHE_TOLERANCE", "900")),
            output_dir=os.getenv("MINERU_OUTPUT_DIR", "resources/parsed_output"),
            max_pages_per_request=int(os.getenv("MINERU_MAX_PAGES_PER_REQUEST", "200")),
        )

    @property
    def project_root(self) -> Path:
        """项目根目录（src 的上一级）"""
        return Path(__file__).resolve().parent.parent

    @property
    def output_path(self) -> Path:
        """解析结果输出目录的绝对路径（相对于项目根目录解析）"""
        p = Path(self.output_dir)
        if p.is_absolute():
            return p
        return self.project_root / p

    @property
    def api_url(self) -> str:
        """精准解析 API 基础 URL"""
        return f"{self.base_url}/api/v4"

    def validate_token(self) -> None:
        """校验 API Token 是否已配置"""
        if not self.api_token or self.api_token == "your_api_token_here":
            raise ValueError(
                "MinerU API Token 未配置，请在 .env 文件中设置 MINERU_API_TOKEN"
            )
