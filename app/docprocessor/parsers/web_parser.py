"""Web page parser using httpx + BeautifulSoup."""

from __future__ import annotations

import time
from typing import Any

import structlog

from app.docprocessor.base import ExtractedSection, ExtractedTable, ExtractionResult

logger = structlog.stdlib.get_logger()

# Tags to strip from parsed HTML (navigation, chrome, ads)
_STRIP_TAGS = {"nav", "footer", "header", "aside", "script", "style", "noscript", "iframe", "svg"}


class WebParser:
    """Extract structured data from web pages using httpx + BeautifulSoup."""

    # Maximum response body size (10 MB) to prevent memory exhaustion.
    _MAX_RESPONSE_SIZE = 10_000_000

    async def parse_url(self, url: str) -> ExtractionResult:
        """Fetch a URL and extract structured content."""
        start = time.monotonic()
        result = ExtractionResult(source_type="url", source_name=url)

        # ── SSRF protection ──────────────────────────────────
        from app.core.url_validation import validate_webhook_url_async

        ssrf_error = await validate_webhook_url_async(url)
        if ssrf_error:
            logger.warning("web_parser_ssrf_blocked", url=url, reason=ssrf_error)
            result.metadata["error"] = f"URL blocked: {ssrf_error}"
            result.extraction_duration_ms = int((time.monotonic() - start) * 1000)
            return result

        try:
            import httpx
        except ImportError:
            logger.error("httpx_not_installed")
            result.metadata["error"] = "httpx is not installed"
            result.extraction_duration_ms = int((time.monotonic() - start) * 1000)
            return result

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.error("beautifulsoup4_not_installed")
            result.metadata["error"] = "beautifulsoup4 is not installed. Install with: pip install beautifulsoup4"
            result.extraction_duration_ms = int((time.monotonic() - start) * 1000)
            return result

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                max_redirects=5,
                headers={"User-Agent": "Nexus-DocProcessor/1.0"},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

            # ── Content-type & size validation ────────────────
            content_type = response.headers.get("content-type", "")
            if not any(ct in content_type for ct in ("text/html", "application/xhtml")):
                result.metadata["error"] = f"Unsupported content type: {content_type}"
                result.extraction_duration_ms = int((time.monotonic() - start) * 1000)
                return result

            if len(response.content) > self._MAX_RESPONSE_SIZE:
                result.metadata["error"] = "Response too large (>10 MB)"
                result.extraction_duration_ms = int((time.monotonic() - start) * 1000)
                return result

            html = response.text
            result.metadata["status_code"] = response.status_code
            result.metadata["content_type"] = response.headers.get("content-type", "")

            soup = BeautifulSoup(html, "html.parser")

            # Remove unwanted tags
            for tag_name in _STRIP_TAGS:
                for tag in soup.find_all(tag_name):
                    tag.decompose()

            # Extract page title
            title_tag = soup.find("title")
            page_title = title_tag.get_text(strip=True) if title_tag else url
            result.metadata["page_title"] = page_title

            # Extract tables
            for html_table in soup.find_all("table"):
                table = self._extract_html_table(html_table)
                if table:
                    result.tables.append(table)

            # Extract sections via heading tags
            text_parts: list[str] = []
            current_section: ExtractedSection | None = None
            content_lines: list[str] = []

            # Try to find main content area
            main = soup.find("main") or soup.find("article") or soup.find("body")
            if main is None:
                main = soup

            for element in main.descendants:
                if not hasattr(element, "name") or element.name is None:
                    continue

                if element.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    # Flush previous section
                    if current_section is not None:
                        current_section.content = "\n".join(content_lines).strip()
                        if current_section.content:
                            result.sections.append(current_section)
                            text_parts.append(
                                f"{'#' * current_section.level} {current_section.title}\n{current_section.content}"
                            )
                        content_lines = []

                    level = int(element.name[1])
                    heading_text = element.get_text(strip=True)
                    current_section = ExtractedSection(
                        title=heading_text,
                        content="",
                        level=level,
                    )

                elif element.name == "p":
                    para_text = element.get_text(strip=True)
                    if para_text:
                        content_lines.append(para_text)
                        if current_section is None:
                            current_section = ExtractedSection(
                                title=page_title,
                                content="",
                                level=1,
                            )

                elif element.name in ("li",):
                    li_text = element.get_text(strip=True)
                    if li_text:
                        content_lines.append(f"- {li_text}")

            # Flush last section
            if current_section is not None:
                current_section.content = "\n".join(content_lines).strip()
                if current_section.content:
                    result.sections.append(current_section)
                    text_parts.append(
                        f"{'#' * current_section.level} {current_section.title}\n{current_section.content}"
                    )

            result.raw_text = (
                "\n\n".join(text_parts) if text_parts else main.get_text(separator="\n", strip=True)[:50000]
            )

        except Exception as exc:
            logger.error("web_extraction_failed", error=str(exc), url=url)
            result.metadata["error"] = str(exc)

        result.extraction_duration_ms = int((time.monotonic() - start) * 1000)
        return result

    @staticmethod
    def _extract_html_table(html_table: Any) -> ExtractedTable | None:
        """Convert an HTML table element to an ExtractedTable."""
        try:
            rows: list[list[str]] = []
            for tr in html_table.find_all("tr"):
                cells = []
                for td in tr.find_all(["th", "td"]):
                    cells.append(td.get_text(strip=True))
                if cells:
                    rows.append(cells)

            if not rows:
                return None

            headers = rows[0]
            data_rows = rows[1:] if len(rows) > 1 else []
            return ExtractedTable(headers=headers, rows=data_rows)
        except Exception:
            return None
