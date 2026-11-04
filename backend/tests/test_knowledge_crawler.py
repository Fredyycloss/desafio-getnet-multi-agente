"""Whole-site crawler: scope, extraction, boilerplate removal, chunking, robots and sitemaps (no network)."""
from bs4 import BeautifulSoup

from app.knowledge.crawler import Crawler, allowed, chunk_pages, extract_page, page_language, remove_boilerplate


def test_allowlist_scope():
    assert allowed("https://site.getnet.com.br/link-de-pagamento/")
    assert allowed("https://www.getnet.net/en/our-solutions/in-person-payments")
    assert allowed("https://www.getnet.net/pt/")
    assert not allowed("https://www.getnet.net/mx/nuestras-soluciones")  # other countries out of scope
    assert not allowed("http://site.getnet.com.br/")  # https only
    assert not allowed("https://evil.example/")
    assert not allowed("https://site.getnet.com.br/wp-content/uploads/x.png")
    assert not allowed("https://site.getnet.com.br/?s=pix")  # query strings (search, tracking) skipped
    assert page_language("https://www.getnet.net/en/contact") == "en" and page_language("https://site.getnet.com.br/pix/") == "pt"


HTML = """<html><head><title>Link de Pagamento | Getnet</title></head><body>
<header><nav>Maquininhas Link Pix</nav></header>
<div class="cookie-banner">Usamos cookies</div>
<article class="card">Acesse o Portal Minha Conta</article>
<div class="content">
 <h1>Link de Pagamento</h1><p>Venda pelo WhatsApp e redes sociais com um link.</p>
 <h2>Formas de pagamento</h2><ul><li>Crédito em até 12x</li><li>Pix e boleto</li></ul>
</div>
<footer>Getnet 2026</footer></body></html>"""


def test_extract_keeps_page_copy_drops_noise_and_ignores_small_article_card():
    page = extract_page(BeautifulSoup(HTML, "html.parser"), "https://site.getnet.com.br/link-de-pagamento/")
    texts = [t for _, t in page["blocks"]]
    assert "Venda pelo WhatsApp e redes sociais com um link." in texts
    assert "Crédito em até 12x" in texts
    assert not any("cookies" in t or "Getnet 2026" in t or "Maquininhas Link Pix" in t for t in texts)
    assert ("h2", "Formas de pagamento") in page["blocks"]
    assert page["title"] == "Link de Pagamento | Getnet" and page["language"] == "pt"


def _page(url, blocks):
    return {"url": url, "title": "T", "breadcrumb": "", "language": "pt", "fetched_at": "x", "blocks": blocks}


def test_text_repeated_on_many_pages_is_removed():
    pages = [_page(f"https://site.getnet.com.br/p{i}/", [("text", "Baixe o App Getnet Brasil"), ("text", f"conteúdo único {i}")])
             for i in range(10)]
    removed = remove_boilerplate(pages)
    assert removed == 10 and all(p["blocks"] == [("text", f"conteúdo único {i}")] for i, p in enumerate(pages))


def test_chunks_follow_headings_split_long_sections_and_dedupe():
    long_text = " ".join(f"palavra{i}" for i in range(1300))
    pages = [_page("https://site.getnet.com.br/a/", [("h2", "Prazos"), ("text", long_text)]),
             _page("https://site.getnet.com.br/b/", [("h2", "Prazos"), ("text", long_text)])]  # duplicate copy
    chunks = chunk_pages(pages, max_words=600, overlap=50)
    assert len(chunks) == 3  # 1300 words -> 3 pieces; the second page is an exact duplicate
    assert all(c["section"] == "Prazos" and c["source_type"] == "official_web_snapshot" for c in chunks)
    assert {"url", "title", "section", "breadcrumb", "language", "fetched_at", "content_hash", "chunk_id"} <= set(chunks[0])
    first, second = chunks[0]["content"].split(), chunks[1]["content"].split()
    assert first[-50:] == second[:50]  # overlap


class FakeResponse:
    def __init__(self, status=200, text="", ctype="text/html", url=""):
        self.status_code, self.text, self.content, self.url = status, text, text.encode(), url
        self.headers = {"content-type": ctype}


class FakeSession:
    def __init__(self, routes):
        self.routes, self.headers, self.requested = routes, {}, []

    def get(self, url, timeout=None, allow_redirects=True):
        self.requested.append(url)
        status, text, ctype = self.routes.get(url, (404, "", "text/html"))
        return FakeResponse(status, text, ctype, url)


def test_robots_disallow_is_respected_and_missing_robots_allows():
    session = FakeSession({"https://www.getnet.net/robots.txt": (200, "User-agent: *\nDisallow: /pt/obrigado", "text/plain")})
    crawler = Crawler(pause=0, session=session)
    assert crawler.robots_allows("https://www.getnet.net/pt/") is True
    assert crawler.robots_allows("https://www.getnet.net/pt/obrigado") is False
    assert crawler.robots_allows("https://site.getnet.com.br/pix/") is True  # robots.txt 404 -> allowed


def test_sitemap_index_is_followed():
    session = FakeSession({
        "https://site.getnet.com.br/sitemap_index.xml": (200, "<sitemapindex><sitemap><loc>https://site.getnet.com.br/post-sitemap.xml</loc></sitemap></sitemapindex>", "text/xml"),
        "https://site.getnet.com.br/post-sitemap.xml": (200, "<urlset><url><loc>https://site.getnet.com.br/blog-a/</loc></url></urlset>", "text/xml"),
    })
    assert Crawler(pause=0, session=session).sitemap_urls("https://site.getnet.com.br/sitemap_index.xml") == ["https://site.getnet.com.br/blog-a/"]
