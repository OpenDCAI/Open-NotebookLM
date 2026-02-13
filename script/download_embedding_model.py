#!/usr/bin/env python3
"""
预下载 Octen/Octen-Embedding-0.6B，避免首次请求时现场拉取。
用法: python script/download_embedding_model.py
"""
from __future__ import annotations

def main():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("请先安装: pip install sentence-transformers")
        return 1
    print("正在下载 Octen/Octen-Embedding-0.6B ...")
    SentenceTransformer("Octen/Octen-Embedding-0.6B")
    print("下载完成，模型已缓存到 Hugging Face 默认目录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
