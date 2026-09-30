"""
MinerU 文档解析工具类

封装 MinerU 精准解析 API，提供完整的文档解析流水线：
  - 自动检测 PDF 页数，超过 200 页自动分段处理
  - 解析完成后自动下载结果并保存到本地
  - 支持单文件和批量处理

所有配置从 .env 文件加载，参见 src/config.py 与 prod.env。

使用示例::

    from src.mineru_parser import MinerUParser

    parser = MinerUParser()

    # 解析单个文件（自动处理大文件，结果保存到本地）
    result = parser.parse_file("./report.pdf")
    print(result["markdown_path"])

    # 批量解析多个文件
    results = parser.parse_files(["a.pdf", "b.pdf"])
"""

import io
import logging
import re
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from src.config import MinerUConfig
from src.exceptions import (
    MinerUApiError,
    MinerUTaskFailedError,
    MinerUTimeoutError,
    MinerUUploadError,
)
from src.models import (
    BatchResult,
    PrecisionBatchUploadFileItem,
    PrecisionBatchUploadRequest,
    PrecisionExtractRequest,
    TaskResponse,
    TaskResult,
)

logger = logging.getLogger(__name__)

# MinerU 精准解析 API 单次请求最大页数
MAX_PAGES_PER_REQUEST = 200


# ================================================================
# PDF 工具函数
# ================================================================

def count_pdf_pages(file_path: str) -> int:
    """
    获取 PDF 文件页数。
    需要安装 PyPDF2: pip install PyPDF2
    """
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(file_path)
        return len(reader.pages)
    except ImportError:
        raise ImportError(
            "需要安装 PyPDF2 来处理 PDF 文件。请执行: pip install PyPDF2"
        )


def split_pdf(file_path: str, start_page: int, end_page: int) -> bytes:
    """
    提取 PDF 指定页码范围的内容，返回新 PDF 的字节数据。
    页码从 1 开始，[start_page, end_page] 两端包含。
    """
    from PyPDF2 import PdfReader, PdfWriter

    reader = PdfReader(file_path)
    writer = PdfWriter()
    # PdfReader.pages 是 0-indexed
    for i in range(start_page - 1, min(end_page, len(reader.pages))):
        writer.add_page(reader.pages[i])

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)
    return output.read()


def compute_page_segments(total_pages: int, max_pages: int = MAX_PAGES_PER_REQUEST) -> List[Tuple[int, int]]:
    """
    计算分页方案。将 total_pages 页按 max_pages 页一段拆分。

    Returns:
        [(start, end), ...] 页码列表，1-indexed，两端包含
    """
    segments = []
    for i in range(0, total_pages, max_pages):
        start = i + 1
        end = min(i + max_pages, total_pages)
        segments.append((start, end))
    return segments


# ================================================================
# 解析器
# ================================================================

class MinerUParser:
    """
    MinerU 文档解析工具类

    核心特性：
      - 自动检测 PDF 页数，超大文件自动分段解析
      - 解析完成后自动下载结果并保存到本地
      - 多段结果自动合并为完整 Markdown
    """

    def __init__(self, config: Optional[MinerUConfig] = None):
        self.config = config or MinerUConfig.from_env()
        self._session = requests.Session()

    # ================================================================
    # 高级接口：解析并保存
    # ================================================================

    def parse_file(self, file_path: str) -> dict:
        """
        解析单个本地文件，自动处理大文件，结果保存到本地。

        不论文件有多少页，都会自动分段解析并合并。
        所有解析参数（模型版本、OCR、公式识别等）从 config 加载。

        Args:
            file_path: 本地文件路径

        Returns:
            dict: {
                "file_name": str,           # 原始文件名
                "total_pages": int,          # 总页数
                "segments": int,             # 分段数
                "output_dir": str,           # 输出目录路径
                "markdown_path": str,        # 合并后 Markdown 文件路径
                "markdown": str,             # Markdown 文本内容
                "segment_results": [         # 每段详情
                    {"file_name": str, "markdown_path": str, "zip_url": str},
                    ...
                ]
            }
        """
        self.config.validate_token()
        file_path = str(Path(file_path).resolve())
        file_name = Path(file_path).name
        stem = Path(file_path).stem

        # 输出目录（基于项目根目录解析的绝对路径）
        out_base = self.config.output_path / stem
        out_base.mkdir(parents=True, exist_ok=True)
        segments_dir = out_base / "segments"

        # 检测页数
        total_pages = count_pdf_pages(file_path)
        max_pages = self.config.max_pages_per_request
        segments = compute_page_segments(total_pages, max_pages)

        logger.info(f"[解析] {file_name}: {total_pages}页, 分为{len(segments)}段")

        if len(segments) == 1:
            # ===== 小文件：直接提交原始文件 =====
            batch_result = self._submit_and_upload_batch(
                file_items=[PrecisionBatchUploadFileItem(name=file_name)],
                file_data=[(file_path, file_name)],
            )
            results = self._wait_and_download_batch(batch_result.batch_id, segments_dir)

            md_path = results[0]["markdown_path"]
            markdown = Path(md_path).read_text(encoding="utf-8") if md_path else ""

            return {
                "file_name": file_name,
                "total_pages": total_pages,
                "segments": 1,
                "output_dir": str(out_base),
                "markdown_path": md_path,
                "markdown": markdown,
                "segment_results": results,
            }

        # ===== 大文件：拆分后分段提交 =====
        segments_dir.mkdir(parents=True, exist_ok=True)

        # 拆分 PDF 并准备数据
        file_items = []
        file_data = []
        segment_pdfs = []

        for idx, (start, end) in enumerate(segments):
            part_name = f"{stem}_part{idx + 1}.pdf"
            pdf_bytes = split_pdf(file_path, start, end)
            # 拆分后的 PDF 是独立文件，从第 1 页开始，无需指定 page_ranges
            file_items.append(PrecisionBatchUploadFileItem(
                name=part_name,
                data_id=f"seg_{idx}",
            ))
            file_data.append((pdf_bytes, part_name))
            segment_pdfs.append((idx, start, end, part_name))

        batch_result = self._submit_and_upload_batch(
            file_items=file_items,
            file_data=file_data,
        )

        # 等待完成并下载
        seg_results = self._wait_and_download_batch(batch_result.batch_id, segments_dir)

        # 按段顺序排序
        seg_results.sort(key=lambda r: self._extract_part_index(r["file_name"]))

        # 合并 Markdown
        final_md_path = str(out_base / f"{stem}.md")
        markdown = self._merge_segment_markdowns(seg_results, final_md_path)

        logger.info(f"[解析] 完成: {file_name}, 输出目录: {out_base}")

        return {
            "file_name": file_name,
            "total_pages": total_pages,
            "segments": len(segments),
            "output_dir": str(out_base),
            "markdown_path": final_md_path,
            "markdown": markdown,
            "segment_results": seg_results,
        }

    def parse_files(self, file_paths: List[str]) -> List[dict]:
        """
        批量解析多个本地文件，每个文件自动处理大小并保存结果。
        所有解析参数从 config 加载。

        Args:
            file_paths: 本地文件路径列表

        Returns:
            List[dict]: 每个文件的解析结果（结构同 parse_file 返回值）
        """
        results = []
        for i, fp in enumerate(file_paths):
            logger.info(f"[批量] 处理文件 ({i + 1}/{len(file_paths)}): {Path(fp).name}")
            try:
                result = self.parse_file(fp)
                results.append(result)
            except Exception as e:
                logger.error(f"[批量] 文件解析失败: {Path(fp).name}, 错误: {e}")
                results.append({
                    "file_name": Path(fp).name,
                    "total_pages": 0,
                    "segments": 0,
                    "output_dir": "",
                    "markdown_path": "",
                    "markdown": "",
                    "segment_results": [],
                    "error": str(e),
                })
        return results

    # ================================================================
    # 便捷方法
    # ================================================================

    def parse_to_markdown(self, file_path: str) -> str:
        """
        解析文件并直接返回 Markdown 文本。

        Args:
            file_path: 本地文件路径

        Returns:
            str: Markdown 文本内容
        """
        result = self.parse_file(file_path)
        return result["markdown"]

    # ================================================================
    # 底层接口（供高级用户直接使用）
    # ================================================================

    def extract_url(self, url: str, wait: bool = True, **kwargs) -> TaskResult:
        """单文件 URL 解析（底层接口）"""
        self.config.validate_token()

        req = PrecisionExtractRequest(
            url=url,
            model_version=kwargs.get("model_version") or self.config.default_model_version,
            is_ocr=kwargs.get("is_ocr", self.config.is_ocr),
            enable_formula=kwargs.get("enable_formula", self.config.enable_formula),
            enable_table=kwargs.get("enable_table", self.config.enable_table),
            language=kwargs.get("language", self.config.language),
            data_id=kwargs.get("data_id"),
            page_ranges=kwargs.get("page_ranges"),
            extra_formats=kwargs.get("extra_formats"),
            no_cache=kwargs.get("no_cache", self.config.no_cache),
            cache_tolerance=kwargs.get("cache_tolerance", self.config.cache_tolerance),
            callback=kwargs.get("callback"),
            seed=kwargs.get("seed"),
        )

        api_url = f"{self.config.api_url}/extract/task"
        resp = self._post(api_url, req.to_dict())
        task_resp = TaskResponse.from_dict(resp)
        task_id = task_resp.task_id

        logger.info(f"[精准解析] 任务已提交, task_id={task_id}, url={url}")

        if not wait:
            return TaskResult(task_id=task_id, state="submitted")

        return self._poll_task(task_id)

    def get_task_result(self, task_id: str) -> TaskResult:
        """查询单任务解析结果"""
        self.config.validate_token()
        api_url = f"{self.config.api_url}/extract/task/{task_id}"
        resp = self._get(api_url)
        return TaskResult.from_dict(resp.get("data", {}))

    def get_batch_result(self, batch_id: str) -> BatchResult:
        """查询批量任务解析结果"""
        self.config.validate_token()
        api_url = f"{self.config.api_url}/extract-results/batch/{batch_id}"
        resp = self._get(api_url)
        return BatchResult.from_dict(resp.get("data", {}))

    # ================================================================
    # 内部方法：批量提交与下载
    # ================================================================

    def _submit_and_upload_batch(
        self,
        file_items: List[PrecisionBatchUploadFileItem],
        file_data: list,
    ) -> BatchResult:
        """
        提交批量上传任务并上传文件。

        Args:
            file_items: 文件项列表（API 请求用）
            file_data: 文件数据列表，每项为 (file_path_or_bytes, file_name)
        """
        req = PrecisionBatchUploadRequest(
            files=file_items,
            model_version=self.config.default_model_version,
        )

        api_url = f"{self.config.api_url}/file-urls/batch"
        resp = self._post(api_url, req.to_dict())
        task_resp = TaskResponse.from_dict(resp)
        batch_id = task_resp.batch_id
        upload_urls = task_resp.file_urls

        logger.info(f"[精准解析] 批量上传任务已创建, batch_id={batch_id}, 文件数={len(file_items)}")

        # 逐个上传文件
        for i, (data, upload_url) in enumerate(zip(file_data, upload_urls)):
            file_source, file_name = data
            if isinstance(file_source, bytes):
                self._upload_bytes(file_source, upload_url)
            else:
                self._upload_file(file_source, upload_url)
            logger.info(f"[精准解析] 文件上传成功 ({i + 1}/{len(file_data)}): {file_name}")

        return BatchResult(batch_id=batch_id)

    def _wait_and_download_batch(
        self,
        batch_id: str,
        save_dir: Path,
    ) -> List[dict]:
        """
        等待批量任务完成，下载每个文件的解析结果并解压。

        Returns:
            List[dict]: 每个文件的结果
                [{"file_name": str, "markdown_path": str, "zip_url": str, "extract_dir": str}, ...]
        """
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        # 轮询等待
        batch_result = self._wait_batch(batch_id)

        results = []
        for item in batch_result.extract_results:
            entry = {
                "file_name": item.file_name,
                "state": item.state,
                "err_msg": item.err_msg,
                "zip_url": item.full_zip_url,
                "markdown_path": "",
                "extract_dir": "",
            }

            if item.state == "done" and item.full_zip_url:
                # 下载并解压
                extract_dir = save_dir / Path(item.file_name).stem
                extract_dir.mkdir(parents=True, exist_ok=True)
                self._download_and_extract_zip(item.full_zip_url, extract_dir)

                # 查找 Markdown 文件
                md_files = list(extract_dir.rglob("*.md"))
                if md_files:
                    entry["markdown_path"] = str(md_files[0])
                    entry["extract_dir"] = str(extract_dir)
                    logger.info(f"[下载] {item.file_name} -> {md_files[0]}")
                else:
                    logger.warning(f"[下载] {item.file_name}: Zip 中未找到 Markdown 文件")

            elif item.state == "failed":
                logger.error(f"[解析失败] {item.file_name}: {item.err_msg}")

            results.append(entry)

        return results

    def _wait_batch(
        self,
        batch_id: str,
        timeout: Optional[int] = None,
        interval: Optional[int] = None,
    ) -> BatchResult:
        """轮询等待批量任务全部完成"""
        self.config.validate_token()

        timeout = timeout or self.config.poll_timeout
        interval = interval or self.config.poll_interval
        start = time.time()

        while time.time() - start < timeout:
            result = self.get_batch_result(batch_id)
            elapsed = int(time.time() - start)

            total = len(result.extract_results)
            done_count = sum(1 for r in result.extract_results if r.state == "done")
            failed_count = sum(1 for r in result.extract_results if r.state == "failed")
            pending_count = total - done_count - failed_count

            if pending_count == 0:
                logger.info(
                    f"[精准解析] 批量任务完成 ({elapsed}s), batch_id={batch_id}, "
                    f"成功={done_count}, 失败={failed_count}"
                )
                return result

            logger.debug(
                f"[精准解析] [{elapsed}s] batch_id={batch_id}, "
                f"完成={done_count}/{total}, 失败={failed_count}, 进行中={pending_count}"
            )
            time.sleep(interval)

        raise MinerUTimeoutError(task_id=batch_id, timeout=timeout)

    # ================================================================
    # 内部方法：下载与合并
    # ================================================================

    def _download_and_extract_zip(self, zip_url: str, extract_dir: Path) -> None:
        """下载 Zip 包并解压到指定目录"""
        resp = self._session.get(zip_url, timeout=120)
        resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            zf.extractall(extract_dir)

    def _merge_segment_markdowns(self, seg_results: List[dict], output_path: str) -> str:
        """合并多段 Markdown 为一个完整文件"""
        parts = []
        for seg in seg_results:
            md_path = seg.get("markdown_path", "")
            if md_path and Path(md_path).is_file():
                content = Path(md_path).read_text(encoding="utf-8")
                parts.append(content)
                logger.debug(f"[合并] 读取段文件: {md_path} ({len(content)} chars)")

        merged = "\n\n".join(parts)
        Path(output_path).write_text(merged, encoding="utf-8")
        logger.info(f"[合并] 已合并 {len(parts)} 段 -> {output_path} ({len(merged)} chars)")
        return merged

    @staticmethod
    def _extract_part_index(file_name: str) -> int:
        """从文件名中提取分段序号，如 'xxx_part2.pdf' -> 2"""
        match = re.search(r"_part(\d+)", file_name)
        return int(match.group(1)) if match else 0

    # ================================================================
    # 内部方法：HTTP 请求
    # ================================================================

    def _headers(self) -> dict:
        """构建请求头"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_token}",
            "Accept": "*/*",
        }

    def _post(self, url: str, data: dict) -> dict:
        """发送 POST 请求并校验响应"""
        resp = self._session.post(url, json=data, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        result = resp.json()

        if result.get("code", -1) != 0:
            raise MinerUApiError(
                message=result.get("msg", "未知错误"),
                code=result.get("code", -1),
                trace_id=result.get("trace_id", ""),
            )
        return result

    def _get(self, url: str) -> dict:
        """发送 GET 请求并校验响应"""
        resp = self._session.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        result = resp.json()

        if result.get("code", -1) != 0:
            raise MinerUApiError(
                message=result.get("msg", "未知错误"),
                code=result.get("code", -1),
                trace_id=result.get("trace_id", ""),
            )
        return result

    def _upload_file(self, file_path: str, upload_url: str) -> None:
        """上传本地文件到 OSS 预签名 URL"""
        with open(file_path, "rb") as f:
            resp = self._session.put(upload_url, data=f, timeout=300)
        if resp.status_code not in (200, 201):
            raise MinerUUploadError(
                message=f"文件上传失败, HTTP {resp.status_code}: {resp.text}",
                code=resp.status_code,
            )

    def _upload_bytes(self, data: bytes, upload_url: str) -> None:
        """上传字节数据到 OSS 预签名 URL"""
        resp = self._session.put(upload_url, data=data, timeout=300)
        if resp.status_code not in (200, 201):
            raise MinerUUploadError(
                message=f"文件上传失败, HTTP {resp.status_code}: {resp.text}",
                code=resp.status_code,
            )

    # ================================================================
    # 内部方法：单任务轮询
    # ================================================================

    def _poll_task(self, task_id: str) -> TaskResult:
        """轮询单任务解析结果"""
        state_labels = {
            "pending": "排队中",
            "running": "解析中",
            "converting": "格式转换中",
        }
        timeout = self.config.poll_timeout
        interval = self.config.poll_interval
        start = time.time()

        while time.time() - start < timeout:
            result = self.get_task_result(task_id)
            elapsed = int(time.time() - start)

            if result.state == "done":
                logger.info(f"[精准解析] 任务完成 ({elapsed}s), task_id={task_id}")
                return result

            if result.state == "failed":
                raise MinerUTaskFailedError(
                    message=result.err_msg or "解析失败",
                    task_id=task_id,
                    trace_id="",
                )

            label = state_labels.get(result.state, result.state)
            progress_info = ""
            if result.extract_progress:
                p = result.extract_progress
                progress_info = f" ({p.extracted_pages}/{p.total_pages}页)"
            logger.debug(f"[精准解析] [{elapsed}s] {label}{progress_info}")

            time.sleep(interval)

        raise MinerUTimeoutError(task_id=task_id, timeout=timeout)
