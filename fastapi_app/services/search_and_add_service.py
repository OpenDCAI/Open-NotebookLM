"""
Search & Add 服务
简单的 Web 搜索 + Top10 爬取功能
"""
import asyncio
import httpx
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from dataflow_agent.logger import get_logger

log = get_logger(__name__)


class SearchAndAddService:
    """Search & Add 服务"""

    def __init__(self):
        self.timeout = 30.0

    async def search_and_crawl(
        self,
        query: str,
        top_k: int = 10,
        search_provider: str = "serper",
        search_api_key: str = None,
    ) -> Dict[str, Any]:
        """
        搜索并爬取 Top K 结果

        Args:
            query: 搜索查询
            top_k: 返回前 K 个结果
            search_provider: 搜索引擎提供商
            search_api_key: 搜索 API 密钥

        Returns:
            {
                "success": bool,
                "query": str,
                "sources": List[{
                    "title": str,
                    "url": str,
                    "snippet": str,
                    "content": str,  # 爬取的完整内容
                    "crawl_success": bool
                }]
            }
        """
        log.info(f"[SearchAndAdd] 开始搜索: {query}, top_k={top_k}")

        try:
            # 1. 执行搜索
            search_results = await self._search(
                query, top_k, search_provider, search_api_key
            )

            if not search_results:
                return {
                    "success": False,
                    "query": query,
                    "sources": [],
                    "error": "搜索未返回结果"
                }

            # 2. 并发爬取所有结果
            crawl_tasks = [
                self._crawl_url(result["url"], result["title"])
                for result in search_results[:top_k]
            ]
            crawled_contents = await asyncio.gather(*crawl_tasks, return_exceptions=True)

            # 3. 合并搜索结果和爬取内容
            sources = []
            for i, result in enumerate(search_results[:top_k]):
                crawl_result = crawled_contents[i]

                if isinstance(crawl_result, Exception):
                    log.warning(f"[SearchAndAdd] 爬取失败 {result['url']}: {crawl_result}")
                    sources.append({
                        **result,
                        "content": result["snippet"],  # 降级使用摘要
                        "crawl_success": False
                    })
                else:
                    sources.append({
                        **result,
                        "content": crawl_result,
                        "crawl_success": True
                    })

            log.info(f"[SearchAndAdd] 完成，成功爬取 {sum(s['crawl_success'] for s in sources)}/{len(sources)} 个页面")

            return {
                "success": True,
                "query": query,
                "sources": sources
            }

        except Exception as e:
            log.error(f"[SearchAndAdd] 执行失败: {e}")
            return {
                "success": False,
                "query": query,
                "sources": [],
                "error": str(e)
            }

    async def _search(
        self,
        query: str,
        top_k: int,
        provider: str,
        api_key: str = None
    ) -> List[Dict[str, str]]:
        """执行搜索"""
        if provider == "serper":
            return await self._search_serper(query, top_k, api_key)
        else:
            raise ValueError(f"不支持的搜索提供商: {provider}")

    async def _search_serper(
        self,
        query: str,
        top_k: int,
        api_key: str = None
    ) -> List[Dict[str, str]]:
        """使用 Serper API 搜索"""
        import os
        api_key = api_key or os.getenv("SERPER_API_KEY")

        if not api_key:
            raise ValueError("SERPER_API_KEY 未配置")

        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "q": query,
            "num": top_k
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        results = []
        for item in data.get("organic", [])[:top_k]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", "")
            })

        return results

    async def _crawl_url(self, url: str, title: str) -> str:
        """
        爬取单个 URL 的内容

        Args:
            url: 目标 URL
            title: 页面标题

        Returns:
            爬取的文本内容（Markdown 格式）
        """
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

            # 解析 HTML
            soup = BeautifulSoup(response.text, "html.parser")

            # 移除脚本和样式
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()

            # 提取主要内容
            # 优先查找常见的内容容器
            main_content = None
            for selector in ["article", "main", ".content", "#content", ".post", ".entry"]:
                main_content = soup.select_one(selector)
                if main_content:
                    break

            if not main_content:
                main_content = soup.body

            if not main_content:
                return f"# {title}\n\n无法提取页面内容"

            # 提取文本
            text = main_content.get_text(separator="\n", strip=True)

            # 清理多余空行
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            text = "\n\n".join(lines)

            # 限制长度（避免过长）
            max_chars = 50000
            if len(text) > max_chars:
                text = text[:max_chars] + "\n\n...(内容已截断)"

            # 格式化为 Markdown
            markdown = f"# {title}\n\n**Source:** {url}\n\n---\n\n{text}"

            return markdown

        except Exception as e:
            log.error(f"[SearchAndAdd] 爬取 {url} 失败: {e}")
            raise

    def format_sources_as_markdown(self, sources: List[Dict[str, Any]]) -> str:
        """将多个来源格式化为单个 Markdown 文档"""
        md_parts = []

        for i, source in enumerate(sources, 1):
            md_parts.append(f"# Source {i}: {source['title']}")
            md_parts.append(f"\n**URL:** {source['url']}")
            md_parts.append(f"\n**Crawl Status:** {'✓ Success' if source['crawl_success'] else '✗ Failed'}")
            md_parts.append("\n---\n")
            md_parts.append(source['content'])
            md_parts.append("\n\n" + "="*80 + "\n\n")

        return "".join(md_parts)
