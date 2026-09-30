import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from src.mineru_parser import MinerUParser

parser = MinerUParser()  # 自动从 .env 加载配置


origin_file = r'D:\mydocument\agent-demo\SparrowRag\resources\pdf_reports\【财报】中芯国际：中芯国际2024年年度报告.pdf'

# 直接调用 parse_file，自动处理任意页数，结果保存到本地
result = parser.parse_file(origin_file)

print(f"文件名: {result['file_name']}")
print(f"总页数: {result['total_pages']}")
print(f"分段数: {result['segments']}")
print(f"输出目录: {result['output_dir']}")
print(f"Markdown路径: {result['markdown_path']}")
print(f"Markdown长度: {len(result['markdown'])} 字符")
