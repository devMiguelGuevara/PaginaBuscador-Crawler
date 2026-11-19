"""Cliente HTTP asíncrono (httpx + HTTP/2) con cadena de redirecciones, reintentos y límite de tamaño."""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from urllib.parse import urljoin

import httpx

from .models import CookieInfo

AUTH_COOKIE_RE = re.compile(r"sess|sid$|^sid|auth|token|jwt|login|remember|user|account|csrf|xsrf|identity|next-auth|sb-", re.I)


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    cookies: list[CookieInfo] = field(default_factory=list)
    body: bytes = b""
    text: str = ""
    content_type: str = ""
    elapsed_ms: float = 0
    http_version: str = ""
    redirect_chain: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def is_html(self) -> bool:
        ct = self.content_type.lower()
        return "html" in ct or (not ct and self.text.lstrip()[:15].lower().startswith(("<!doctype", "<html")))


def parse_set_cookie(values: list[str], default_domain: str) -> list[CookieInfo]:
    out: list[CookieInfo] = []
    for raw in values:
        low = raw.lower()
        try:
            jar = SimpleCookie()
            jar.load(raw)
        except Exception:
            jar = None
        names = list(jar.keys()) if jar else [raw.split("=", 1)[0].strip()]
        for name in names[:1]:  # un Set-Cookie = una cookie
            morsel = jar[name] if jar else None
            same_site = ""
            m = re.search(r"samesite=(\w+)", low)
            if m:
                same_site = m.group(1).capitalize()
            out.append(CookieInfo(
                name=name,
                domain=(morsel["domain"] if morsel and morsel["domain"] else default_domain),
                path=(morsel["path"] if morsel and morsel["path"] else "/"),
                secure="secure" in [p.strip() for p in low.split(";")],
                http_only="httponly" in low,
                same_site=same_site,
                session=not ("expires=" in low or "max-age=" in low),
                source="header",
                auth_hint=bool(AUTH_COOKIE_RE.search(name)),
            ))
    return out


class Fetcher:
    def __init__(self, user_agent: str, timeout: float = 20.0, max_body_bytes: int = 5_000_000,
                 max_connections: int = 16, retries: int = 2):
        self.max_body_bytes = max_body_bytes
        self.retries = retries
        self.client = httpx.AsyncClient(
            http2=True,
            follow_redirects=False,
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
            limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections),
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            },
            verify=True,
        )

    async def __aenter__(self) -> "Fetcher":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self.client.aclose()

    async def fetch(self, url: str, max_redirects: int = 10) -> FetchResult:
        result = FetchResult(url=url)
        current = url
        started = time.perf_counter()
        for _ in range(max_redirects + 1):
            resp, err = await self._get(current)
            if err:
                result.error = err
                result.final_url = current
                break
            host = resp.url.host or ""
            result.cookies.extend(parse_set_cookie(resp.headers.get_list("set-cookie"), host))
            if resp.is_redirect and "location" in resp.headers:
                result.redirect_chain.append(f"{resp.status_code} {current}")
                current = urljoin(current, resp.headers["location"])
                await resp.aclose()
                continue
            result.status = resp.status_code
            result.final_url = str(resp.url)
            result.headers = {k.lower(): v for k, v in resp.headers.items()}
            result.content_type = resp.headers.get("content-type", "")
            result.http_version = resp.http_version
            try:
                chunks, size = [], 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > self.max_body_bytes:
                        break
                result.body = b"".join(chunks)
            finally:
                await resp.aclose()
            if self._is_textual(result.content_type) or not result.content_type:
                result.text = self._decode(result.body, resp)
            break
        else:
            result.error = "Demasiadas redirecciones"
            result.final_url = current
        result.elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        return result

    async def _get(self, url: str) -> tuple[httpx.Response | None, str | None]:
        last_err = None
        for attempt in range(self.retries + 1):
            try:
                req = self.client.build_request("GET", url)
                resp = await self.client.send(req, stream=True)
                if resp.status_code in (429, 502, 503, 504) and attempt < self.retries:
                    await resp.aclose()
                    delay = 1.5 * (attempt + 1)
                    ra = resp.headers.get("retry-after", "")
                    if ra.isdigit():
                        delay = min(float(ra), 10.0)
                    await asyncio.sleep(delay)
                    continue
                return resp, None
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as e:
                last_err = f"{type(e).__name__}: {e}".strip()
                if attempt < self.retries:
                    await asyncio.sleep(1.0 * (attempt + 1))
            except httpx.HTTPError as e:
                return None, f"{type(e).__name__}: {e}"
        return None, last_err or "Error de red"

    async def fetch_text(self, url: str) -> tuple[int | None, str]:
        r = await self.fetch(url)
        return r.status, r.text

    @staticmethod
    def _is_textual(ct: str) -> bool:
        ct = ct.lower()
        return any(t in ct for t in ("text/", "html", "xml", "json", "javascript", "css"))

    @staticmethod
    def _decode(body: bytes, resp: httpx.Response) -> str:
        enc = resp.charset_encoding
        if not enc:
            m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:2048], re.I)
            enc = m.group(1).decode() if m else "utf-8"
        try:
            return body.decode(enc, errors="replace")
        except LookupError:
            return body.decode("utf-8", errors="replace")
