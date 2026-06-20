"""
📚 个人知识库 — 纯 Python 实现
TF-IDF 向量搜索，无需任何第三方包
"""

import os
import re
import math
import json
import glob
from collections import Counter, defaultdict
from typing import List, Dict, Tuple
import io


class KnowledgeBase:
    """轻量级本地知识库：TF-IDF + 余弦相似度"""

    def __init__(self, kb_path: str = "~/agent_knowledge"):
        self.kb_path = os.path.expanduser(kb_path)
        self.documents: List[Dict] = []  # [{id, title, content, source}]
        self.index_path = os.path.join(self.kb_path, "index.json")
        self.docs_path = os.path.join(self.kb_path, "documents.json")
        self._ensure_dir()
        self._load()

    def _ensure_dir(self):
        os.makedirs(self.kb_path, exist_ok=True)

    # ── 文档管理 ──

    def add_text(self, title: str, content: str, source: str = "笔记") -> str:
        """添加一段文本到知识库"""
        doc = {
            "id": str(len(self.documents)),
            "title": title,
            "content": content,
            "source": source,
        }
        self.documents.append(doc)
        self._save()
        return f"✅ 已添加「{title}」({len(content)} 字符)"

    def add_file(self, file_path: str) -> str:
        """添加一个文本文件到知识库"""
        path = os.path.expanduser(file_path)
        if not os.path.exists(path):
            return f"❌ 文件不存在: {file_path}"
        if os.path.isdir(path):
            return self._add_directory(path)
        return self._add_single_file(path)

    def _add_single_file(self, path: str) -> str:
        name = os.path.basename(path)
        try:
            if path.lower().endswith(".pdf"):
                return self._add_pdf(path, name)
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            # 按段落分块（每块不超过2000字）
            chunks = self._chunk_text(content, max_chars=2000)
            added = 0
            for i, chunk in enumerate(chunks):
                suffix = f" (第{i+1}段)" if len(chunks) > 1 else ""
                self.documents.append({
                    "id": str(len(self.documents)),
                    "title": f"{name}{suffix}",
                    "content": chunk.strip(),
                    "source": path,
                })
                added += 1
            self._save()
            return f"✅ 已导入 {name}（{added} 段，共 {len(content)} 字符）"
        except Exception as e:
            return f"❌ 读取 {name} 失败: {e}"

    def _add_directory(self, path: str) -> str:
        results = []
        for root, _, files in os.walk(path):
            for f in files:
                if f.endswith((".txt", ".md", ".py", ".json", ".yaml", ".yml", ".csv", ".pdf")):
                    fp = os.path.join(root, f)
                    results.append(self._add_single_file(fp))
        return "\n".join(results[:20])  # 最多返回20条

    def _add_pdf(self, path: str, name: str) -> str:
        """解析 PDF 并导入知识库"""
        try:
            from pypdf import PdfReader
            reader = PdfReader(path)
            text = ""
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                text += f"\n--- 第 {i+1} 页 ---\n{page_text}"

            if not text.strip():
                return f"⚠️ {name} 未能提取到文字（可能是扫描件/图片PDF）"

            chunks = self._chunk_text(text, max_chars=2000)
            added = 0
            for i, chunk in enumerate(chunks):
                suffix = f" (第{i+1}段)" if len(chunks) > 1 else ""
                self.documents.append({
                    "id": str(len(self.documents)),
                    "title": f"{name}{suffix}",
                    "content": chunk.strip(),
                    "source": path,
                })
                added += 1
            self._save()
            return f"✅ 已导入 PDF: {name}（{added} 段，共 {len(text)} 字符，{len(reader.pages)} 页）"
        except ImportError:
            return "❌ 需要安装 pypdf: pip install pypdf"
        except Exception as e:
            return f"❌ 解析 PDF {name} 失败: {e}"

    def _chunk_text(self, text: str, max_chars: int = 2000) -> List[str]:
        """按段落分块"""
        paragraphs = text.split("\n\n")
        chunks = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) < max_chars:
                current += p + "\n\n"
            else:
                if current.strip():
                    chunks.append(current.strip())
                current = p + "\n\n"
        if current.strip():
            chunks.append(current.strip())
        return chunks if chunks else [text]

    def list_docs(self) -> str:
        """列出知识库中的所有文档"""
        if not self.documents:
            return "📚 知识库是空的"
        result = [f"📚 知识库共 {len(self.documents)} 段文档:\n"]
        for i, doc in enumerate(self.documents):
            title = doc["title"][:40]
            content_preview = doc["content"][:50].replace("\n", " ")
            result.append(f"  {i+1}. {title}")
            result.append(f"     📝 {content_preview}...")
        return "\n".join(result)

    def clear(self) -> str:
        """清空知识库"""
        self.documents = []
        self._save()
        return "🗑️ 知识库已清空"

    # ── 管理接口（给 Web UI 用）──

    def get_doc(self, doc_id: str) -> dict | None:
        """按 ID 获取单篇文档"""
        for doc in self.documents:
            if doc["id"] == doc_id:
                return doc
        return None

    def delete_doc(self, doc_id: str) -> bool:
        """按 ID 删除文档"""
        for i, doc in enumerate(self.documents):
            if doc["id"] == doc_id:
                self.documents.pop(i)
                self._save()
                return True
        return False

    def update_doc(self, doc_id: str, title: str = None, content: str = None) -> bool:
        """更新文档标题和/或内容"""
        for doc in self.documents:
            if doc["id"] == doc_id:
                if title is not None:
                    doc["title"] = title
                if content is not None:
                    doc["content"] = content
                self._save()
                return True
        return False

    def search_raw(self, query: str, top_k: int = 5) -> list:
        """搜索，返回原始 [(doc, score), ...] 列表（不走高亮格式化）"""
        if not self.documents or not query.strip():
            return []
        tokens = self._tokenize(query)
        if not tokens:
            return []
        return self._tfidf_search(tokens, top_k)

    # ── TF-IDF 搜索 ──

    def search(self, query: str, top_k: int = 5) -> str:
        """
        搜索知识库，返回最相关的文档片段
        
        Args:
            query: 搜索关键词
            top_k: 返回结果数量
        
        Returns:
            格式化的搜索结果
        """
        if not self.documents:
            return "📚 知识库是空的，请先添加文档"
        if not query.strip():
            return "请输入搜索关键词"

        # 1. 分词
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return "未识别到有效的搜索词"

        # 2. 计算 TF-IDF 并排序
        results = self._tfidf_search(query_tokens, top_k)

        if not results:
            return f"未找到与「{query}」相关的内容"

        output = [f"🔍 找到 {len(results)} 条相关结果:\n"]
        for i, (doc, score) in enumerate(results):
            title = doc["title"]
            # 高亮匹配词
            snippet = self._highlight(doc["content"][:500], query_tokens)
            output.append(f"{'='*40}")
            output.append(f"📄 {title} (相关度: {score:.0%})")
            output.append(f"📎 {doc['source']}")
            output.append(f"{snippet}\n")

        return "\n".join(output)

    def _tokenize(self, text: str) -> List[str]:
        """分词：中文按字/词，英文按单词"""
        text = text.lower()
        # 提取中文字符（每个字作为一个 token）
        chinese = re.findall(r'[\u4e00-\u9fff]', text)
        # 提取英文单词
        english = re.findall(r'[a-z]+', text)
        # 提取数字
        numbers = re.findall(r'\d+', text)
        return chinese + [w for w in english if len(w) > 1] + numbers

    def _tfidf_search(self, query_tokens: List[str], top_k: int) -> List[Tuple[Dict, float]]:
        """TF-IDF 搜索"""
        n_docs = len(self.documents)

        # 计算每个文档的 TF
        doc_tfs = []
        for doc in self.documents:
            tokens = self._tokenize(doc["content"])
            tf = Counter(tokens)
            doc_tfs.append(tf)

        # 计算 IDF
        idf = {}
        for token in query_tokens:
            df = sum(1 for tf in doc_tfs if tf.get(token, 0) > 0)
            idf[token] = math.log((n_docs + 1) / (df + 1)) + 1

        # 计算每个文档的 TF-IDF 分数
        scored = []
        for i, doc in enumerate(self.documents):
            tf = doc_tfs[i]
            score = 0
            for token in query_tokens:
                score += tf.get(token, 0) * idf.get(token, 0)
            if score > 0:
                # 归一化
                doc_len = max(1, sum(tf.values()))
                score = score / math.sqrt(doc_len)
                scored.append((doc, score))

        # 排序
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def _highlight(self, text: str, tokens: List[str], max_len: int = 500) -> str:
        """高亮匹配的关键词"""
        if len(text) > max_len:
            text = text[:max_len] + "..."

        # 简单高亮（用 ** 包围匹配词）
        lower_text = text.lower()
        for token in sorted(tokens, key=len, reverse=True):
            if token in lower_text:
                idx = lower_text.index(token)
                text = text[:idx] + "**" + text[idx:idx+len(token)] + "**" + text[idx+len(token):]
                lower_text = text.lower()

        return text

    # ── 持久化 ──

    def _save(self):
        with open(self.docs_path, "w", encoding="utf-8") as f:
            json.dump(self.documents, f, ensure_ascii=False, indent=2)

    def _load(self):
        if os.path.exists(self.docs_path):
            try:
                with open(self.docs_path, "r", encoding="utf-8") as f:
                    self.documents = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                self.documents = []
