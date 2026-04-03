"""
pytest 配置 — 路径设置，让 app.* 导入可用
"""
import sys
from pathlib import Path

# 将 backend/ 目录加入 Python path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))
