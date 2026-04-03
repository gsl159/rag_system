"""
文档处理服务
流程：上传 → MinIO → 解析 → 清洗 → 分块 → 质量评估 → 向量入库
"""
import os
import re
import uuid
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Tuple

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import logger
from app.core.llm import embed_client
from app.db.postgres import Document, Chunk
from app.db.milvus import milvus_db
from app.db.minio import minio_storage
from app.rag.retriever import retriever


class DocParser:
    """文档解析 — 支持 PDF / Word / HTML / TXT / MD"""

    def parse(self, file_path: str) -> str:
        suffix = Path(file_path).suffix.lower()
        try:
            from unstructured.partition.auto import partition
            elements = partition(file_path)
            texts    = [el.text for el in elements if hasattr(el, "text") and el.text]
            return "\n".join(texts)
        except Exception as e:
            logger.warning(f"unstructured 解析失败 ({suffix}): {e}，回退纯文本")
            return self._fallback_parse(file_path, suffix)

    def _fallback_parse(self, path: str, suffix: str) -> str:
        try:
            if suffix in (".html", ".htm"):
                from html.parser import HTMLParser
                class _Strip(HTMLParser):
                    def __init__(self):
                        super().__init__(); self.parts = []
                    def handle_data(self, d): self.parts.append(d)
                p = _Strip()
                p.feed(Path(path).read_text("utf-8", errors="ignore"))
                return " ".join(p.parts)
            return Path(path).read_text("utf-8", errors="ignore")
        except Exception as e:
            logger.error(f"回退解析也失败: {e}")
            return ""


class TextCleaner:
    """文本清洗"""

    def clean(self, text: str) -> str:
        text = re.sub(r"\r\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {3,}", " ", text)
        # 保留 ASCII + 中文 + 标点
        text = re.sub(
            r"[^\x09\x0a\x0d\x20-\x7e"
            r"\u4e00-\u9fa5\u3000-\u303f\uff00-\uffef"
            r"\u2014-\u2027]",
            "", text,
        )
        return text.strip()


class TextSplitter:
    """滑动窗口分块，优先在句末断开"""

    def __init__(self, chunk_size: int = None, overlap: int = None):
        self.chunk_size = chunk_size or settings.CHUNK_SIZE
        self.overlap    = overlap    or settings.CHUNK_OVERLAP

    def split(self, text: str) -> List[str]:
        chunks = []
        start  = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            if end < len(text):
                for sep in ["。", "！", "？", "\n\n", ".", "!", "?", "\n"]:
                    pos = text.rfind(sep, start + self.chunk_size // 2, end)
                    if pos != -1:
                        end = pos + 1
                        break
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start = end - self.overlap
        return chunks


class QualityChecker:
    """文档质量评估"""

    def evaluate(self, chunks: List[str]) -> Dict[str, Any]:
        if not chunks:
            return {"score": 0.0, "valid_ratio": 0.0, "avg_length": 0, "total": 0, "valid": 0}
        valid   = [c for c in chunks if len(c.strip()) >= 20]
        avg_len = sum(len(c) for c in chunks) / len(chunks)
        # 综合评分：有效比例 * 0.7 + 平均长度分 * 0.3
        len_score = min(avg_len / 200, 1.0)
        score     = len(valid) / len(chunks) * 0.7 + len_score * 0.3
        return {
            "score":       round(score, 4),
            "valid_ratio": round(len(valid) / len(chunks), 4),
            "avg_length":  round(avg_len, 1),
            "total":       len(chunks),
            "valid":       len(valid),
        }


# ── 服务入口 ──────────────────────────────────

class DocumentService:
    def __init__(self):
        self.parser  = DocParser()
        self.cleaner = TextCleaner()
        self.splitter= TextSplitter()
        self.checker = QualityChecker()

    async def process(self, doc_id: str, file_path: str, db: AsyncSession):
        logger.info(f"开始处理文档 doc_id={doc_id}")
        await self._set_status(db, doc_id, "processing")

        try:
            # 1. 解析
            raw  = self.parser.parse(file_path)
            if not raw:
                raise ValueError("文档内容为空，无法解析")

            # 2. 清洗
            text = self.cleaner.clean(raw)

            # 3. 分块
            chunks = self.splitter.split(text)

            # 4. 质量评估
            quality = self.checker.evaluate(chunks)
            logger.info(f"文档 {doc_id} 质量: {quality}")

            if quality["score"] < settings.QUALITY_THRESHOLD:
                raise ValueError(
                    f"质量分 {quality['score']:.2f} < 阈值 {settings.QUALITY_THRESHOLD}，拒绝入库"
                )

            # 5. Embedding
            embeddings = await embed_client.embed_batch(chunks)

            # 6. Milvus 入库
            chunk_ids  = [str(uuid.uuid4()) for _ in chunks]
            milvus_db.insert(
                ids        = chunk_ids,
                doc_ids    = [doc_id] * len(chunks),
                chunk_idxs = list(range(len(chunks))),
                texts      = chunks,
                embeddings = embeddings,
            )

            # 7. BM25 索引更新
            retriever.add_texts(chunks)

            # 8. PostgreSQL 入库
            chunk_rows = [
                Chunk(
                    id        = chunk_ids[i],
                    doc_id    = doc_id,
                    content   = chunks[i],
                    chunk_idx = i,
                    char_count= len(chunks[i]),
                    meta_info  = {"doc_id": doc_id, "idx": i},
                )
                for i in range(len(chunks))
            ]
            db.add_all(chunk_rows)

            # 9. 更新文档状态
            await db.execute(
                update(Document).where(Document.id == doc_id).values(
                    status      = "done",
                    parse_score = quality["score"],
                    chunk_count = len(chunks),
                )
            )
            await db.commit()
            logger.info(f"文档 {doc_id} 处理完成，{len(chunks)} 个 chunk")

        except Exception as e:
            logger.error(f"文档 {doc_id} 处理失败: {e}")
            await self._set_status(db, doc_id, "failed", str(e))
            raise

    async def _set_status(self, db: AsyncSession, doc_id: str, status: str, error: str = None):
        vals = {"status": status}
        if error:
            vals["error_msg"] = error[:500]
        await db.execute(update(Document).where(Document.id == doc_id).values(**vals))
        await db.commit()


doc_service = DocumentService()
