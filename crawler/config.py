"""Configuración de un rastreo."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RenderMode = Literal["auto", "always", "never"]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36 PaginaBuscadorCrawler/0.1"
)


class CrawlConfig(BaseModel):
    start_url: str
    max_pages: int = Field(100, ge=1, le=5000)
    max_depth: int = Field(5, ge=0, le=50)
    concurrency: int = Field(8, ge=1, le=64)
    delay: float = Field(0.0, ge=0, description="Segundos de espera entre peticiones de cada worker")
    timeout: float = Field(20.0, gt=0)
    render: RenderMode = "auto"
    render_concurrency: int = Field(3, ge=1, le=10)
    respect_robots: bool = True
    include_subdomains: bool = False
    use_sitemap: bool = True
    screenshots: int = Field(6, ge=0, le=100, description="Páginas con captura (home + una por área)")
    pdf: bool = False
    output_dir: str = "output"
    user_agent: str = DEFAULT_USER_AGENT
    max_body_bytes: int = 5_000_000
