"""读复制来的论文链接：DOI/arXiv 走元数据接口，普通网页抽正文。

只做「能不能读到」这一件事，读不到就如实说读不到（付费墙、需要 JS、只有题名），
不猜内容——讲解交回给模型，本模块只负责把可信的文字取回来。
"""
import html as _html
import json
import re
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0 Safari/537.36 ShizukaPaperReader/0.1")
MAX_BYTES = 1536 * 1024       # 单个页面最多读 1.5MB（大页面下载太久，够用就行）
MAX_TEXT = 12000              # 正文摘录上限（够模型判断，又不至于塞爆上下文）
TIMEOUT = 15

DOI_RE = re.compile(r"(?:doi\.org/|doi:\s*|dx\.doi\.org/)?\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", re.I)
ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([A-Za-z\-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", re.I)

# 常见论文站点：只是「可能是论文」的提示，真正的判据是页面里的 citation_* 元数据或 DOI
PAPER_HOSTS = (
    "arxiv.org", "doi.org", "dx.doi.org", "ncbi.nlm.nih.gov", "pmc.ncbi.nlm.nih.gov", "europepmc.org",
    "link.springer.com", "www.nature.com", "nature.com", "science.org", "www.science.org",
    "www.sciencedirect.com", "ieeexplore.ieee.org", "dl.acm.org", "onlinelibrary.wiley.com",
    "pubs.acs.org", "pubs.rsc.org", "journals.sagepub.com", "www.tandfonline.com", "www.mdpi.com",
    "journals.plos.org", "www.pnas.org", "www.biorxiv.org", "www.medrxiv.org", "www.frontiersin.org",
    "iopscience.iop.org", "www.osti.gov", "hal.science", "www.researchgate.net", "papers.ssrn.com",
    "www.aps.org", "journals.aps.org", "www.cell.com", "www.thelancet.com", "www.bmj.com",
    "academic.oup.com", "www.degruyter.com", "www.worldscientific.com", "www.emerald.com",
    "www.spiedigitallibrary.org", "ascelibrary.org", "www.tandfonline.com", "scholar.google.com",
    "openreview.net", "www.semanticscholar.org", "www.jstor.org", "www.annualreviews.org",
)

REASON_LINES = {
    "bad-url": "这个链接我看不出是论文，换成论文的网页地址再给我一次？",
    "pdf": "这是 PDF 链接，我这边读不了 PDF 正文。要是有网页版（摘要页）的地址，发那个我就能看。",
    "no-network": "这个网页我没打开（网络没通或者站点拦了），等下再试一次？",
    "not-found": "这个地址打不开呢，可能是链接不全，或者这篇查不到。你再确认一下？",
    "blocked": "这个站点不让自动读取（大概要登录或者有反爬限制），正文我拿不到。",
    "not-paper": "这个页面我没看出是论文，只有普通的网页内容。你确认一下地址？",
    "paywall": "正文抓不到呢——这篇大概要订阅或者得先登录，我这边只看得到题名和公开摘要。",
    "title-only": "只拿到题名，公开摘要也没抓到，我只能凭题名猜，不编内容。",
}


def strip_tags(raw):
    """把 HTML 片段压成一行纯文本（供摘要、作者名这类短字段用）。"""
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", str(raw or ""))
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def find_url(text):
    """从剪贴板文本里挑出第一个 http(s) 链接。"""
    match = re.search(r"https?://[^\s\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+", text or "")
    return match.group(0).rstrip(".,;:!?)]}>\"'") if match else ""


def doi_in(text):
    match = DOI_RE.search(text or "")
    if not match:
        return ""
    return match.group(1).rstrip(".,;:)]}>\"'").lower()


def arxiv_in(text):
    match = ARXIV_RE.search(text or "")
    return match.group(1) if match else ""


def looks_like_paper(text):
    """剪贴板里的东西值不值得按「论文」处理：域名像论文站，或者文本里有 DOI / arXiv 号。"""
    raw = (text or "").strip()
    if not raw or len(raw) > 2000:
        return False
    url = find_url(raw) or raw
    host = urllib.parse.urlparse(url).netloc.lower()
    if host:
        host = host[4:] if host.startswith("www.") else host
        if any(host == h or host.endswith("." + h) for h in PAPER_HOSTS):
            return True
    if doi_in(raw) or arxiv_in(raw):
        return True
    return bool(re.search(r"/(?:doi|abs|article|paper|publication)/", url, re.I))


# ---------------- 取数据 ----------------

def _decode(raw, charset=""):
    for encoding in ([charset] if charset else []) + ["utf-8", "gb18030", "latin-1"]:
        try:
            return raw.decode(encoding, "ignore")
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "ignore")


def _read(opener, url, timeout=TIMEOUT, headers=None):
    """取一个 URL，返回 (最终地址, 文本, 内容类型)；失败返回 ('', '', '')。
    HTTP 状态错误时内容类型写成 error:<状态码>，好让上层分清「地址不对」和「网络不通」。"""
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*",
                                                   "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                                                   **(headers or {})})
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raw = raw[:MAX_BYTES]
            final = getattr(response, "url", "") or getattr(response, "geturl", lambda: url)()
            ctype = ""
            try:
                ctype = response.headers.get("Content-Type", "") or ""
            except Exception:
                ctype = ""
    except urllib.error.HTTPError as exc:
        return getattr(exc, "url", "") or url, "", "error:%s" % (getattr(exc, "code", "") or "?")
    except Exception:
        return "", "", ""
    if not raw:
        return final, "", ctype
    charset = ""
    match = re.search(r"charset=([\w\-]+)", ctype, re.I)
    if match:
        charset = match.group(1)
    if not charset:
        match = re.search(rb'charset=["\']?([\w\-]+)', raw[:4000], re.I)
        if match:
            charset = match.group(1).decode("ascii", "ignore")
    return final, _decode(raw, charset), ctype


def _json(opener, url, timeout=20):
    _, text, _ = _read(opener, url, timeout, headers={"Accept": "application/json"})
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _meta_tags(page):
    """Highwire 的 citation_* 元数据：多数出版社的论文页都带。"""
    meta = {}
    for match in re.finditer(r"<meta\s+([^>]+)>", page or "", re.I):
        attrs = match.group(1)
        name = re.search(r'(?:name|property)\s*=\s*["\']([^"\']+)["\']', attrs, re.I)
        content = re.search(r'content\s*=\s*["\']([^"\']*)["\']', attrs, re.I)
        if not name or content is None:
            continue
        key = name.group(1).strip().lower()
        value = _html.unescape(content.group(1)).strip()
        if not value:
            continue
        meta.setdefault(key, []).append(value)
    return meta


def _first(meta, *keys):
    for key in keys:
        values = meta.get(key) or []
        if values:
            return strip_tags(values[0])
    return ""


def clean_body(text, min_len=40):
    """正文清洗：导航/菜单/按钮这类短行丢掉，只留成段的文字（arXiv 摘要页的正文几乎全是导航）。"""
    lines = []
    for raw in (text or "").split("\n"):
        line = re.sub(r"\s+", " ", raw).strip()
        if len(line) >= min_len:
            lines.append(line)
    return "\n".join(lines).strip()


def _article_text(page):
    """抽正文：优先 <article>/<main>，否则整页可见文字。"""
    body = page or ""
    for pattern in (r"(?is)<article[^>]*>(.*?)</article>", r"(?is)<main[^>]*>(.*?)</main>"):
        match = re.search(pattern, body)
        if match and len(match.group(1)) > 800:
            body = match.group(1)
            break
    text = re.sub(r"(?is)<(script|style|noscript|nav|footer|header|form|svg)[^>]*>.*?</\1>", " ", body)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</(p|div|li|h[1-6]|tr|section)>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _abstract_from_text(text):
    """正文里找 Abstract / 摘要 那一段。"""
    match = re.search(r"(?im)^\s*(?:abstract|summary|摘\s*要)\s*[:：]?\s*$", text or "")
    if not match:
        match = re.search(r"(?im)(?:abstract|摘\s*要)\s*[:：]\s*", text or "")
        if not match:
            return ""
        return re.split(r"\n\s*(?:keywords?|关键词|1\.?\s+introduction|引言)\b",
                        text[match.end():], maxsplit=1)[0].strip()[:4000]
    tail = text[match.end():]
    return re.split(r"\n\s*(?:keywords?|关键词|1\.?\s+introduction|引言|introduction)\b",
                    tail, maxsplit=1, flags=re.I)[0].strip()[:4000]


def _crossref(doi, opener):
    data = _json(opener, "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/"))
    message = (data or {}).get("message") or {}
    title = strip_tags((message.get("title") or [""])[0])
    if not title and not message.get("abstract"):
        return None
    dates = []
    for key in ("published-online", "published-print", "published", "issued"):
        parts = (message.get(key) or {}).get("date-parts") or []
        try:
            if parts and len(parts[0]) == 3:
                dates.append("%04d-%02d-%02d" % tuple(parts[0]))
        except (TypeError, ValueError):
            continue
    authors = []
    for person in (message.get("author") or [])[:6]:
        name = " ".join(x for x in (person.get("given"), person.get("family")) if x)
        if name:
            authors.append(name)
    return {"title": title, "journal": strip_tags((message.get("container-title") or [""])[0]),
            "date": min(dates) if dates else "", "authors": authors,
            "abstract": strip_tags(message.get("abstract")), "source": "Crossref",
            "url": "https://doi.org/" + urllib.parse.quote(doi, safe="/")}


def _arxiv_abs_url(ident):
    """arXiv 的 API 对自动请求常返回 406，直接用摘要页（页面自带 citation_* 元数据）。"""
    return "https://arxiv.org/abs/" + ident


def _from_page(url, opener):
    final, page, ctype = _read(opener, url)
    if (ctype or "").startswith("error:"):
        return {"http_error": (ctype or "")[6:], "url": final or url}
    if not page:
        return None
    if "application/pdf" in (ctype or "").lower():
        return {"pdf": True, "url": final or url}
    meta = _meta_tags(page)
    title = _first(meta, "citation_title", "dc.title", "og:title", "twitter:title")
    if not title:
        match = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
        title = strip_tags(match.group(1)) if match else ""
    text = _article_text(page)
    abstract = _first(meta, "citation_abstract", "dc.description", "description", "og:description")
    if not abstract:
        abstract = _abstract_from_text(text)
    authors = meta.get("citation_author") or meta.get("dc.creator") or []
    authors = [strip_tags(a) for a in authors][:6]
    looks_like_paper = bool(_first(meta, "citation_title", "citation_doi", "citation_journal_title")
                            or re.search(r"(?i)\b(abstract|摘要)\b", page))
    return {"title": title, "journal": _first(meta, "citation_journal_title", "dc.source", "og:site_name"),
            "date": _first(meta, "citation_publication_date", "citation_online_date", "dc.date")[:10],
            "authors": authors, "abstract": abstract, "text": clean_body(text)[:MAX_TEXT],
            "source": "网页", "url": final or url, "looks_like_paper": looks_like_paper,
            "pdf": False}


def read_paper(url, opener=urllib.request.urlopen):
    """读一篇论文：返回统一结构（readable=False 时 reason 说明为什么读不到）。"""
    raw = (url or "").strip()
    result = {"url": raw, "title": "", "journal": "", "date": "", "authors": [],
              "abstract": "", "text": "", "source": "", "readable": False, "reason": ""}
    link = find_url(raw) or raw
    if not re.match(r"^https?://", link, re.I):
        if doi_in(raw):
            link = "https://doi.org/" + doi_in(raw)
        else:
            result["reason"] = "bad-url"
            return result
    result["url"] = link
    doi = doi_in(link)
    if doi:
        meta = _crossref(doi, opener)
        if meta:
            result.update({k: v for k, v in meta.items() if v})
    arxiv = arxiv_in(link)
    if arxiv and (not result["title"] or link.lower().endswith(".pdf")):
        # PDF 链接换成摘要页，这样至少能拿到题名和摘要（不下载 PDF 正文）
        link = _arxiv_abs_url(arxiv)
        result["url"] = link
    if len(result["abstract"]) >= 200:
        result["readable"] = True
        return result
    if link.lower().endswith(".pdf"):
        result["reason"] = "pdf"
        return result
    # 元数据里的摘要太短或没有 → 再去抓页面（开放获取的网页能拿到正文）
    page = _from_page(link, opener)
    if page is None:
        result["reason"] = "title-only" if result["title"] else "no-network"
        return result
    if page.get("pdf"):
        result.update({"reason": "pdf", "url": page.get("url") or link})
        return result
    if page.get("http_error"):
        code = str(page.get("http_error"))
        result["url"] = page.get("url") or link
        if code.startswith("4"):
            result["reason"] = "blocked" if code in ("401", "403", "429") else "not-found"
        else:
            result["reason"] = "no-network"
        return result
    for key in ("title", "journal", "date", "authors", "abstract", "text", "source"):
        if key == "abstract":
            # 摘要取更全的那份（元数据里的常常被截短）
            page_abstract = page.get("abstract") or ""
            if len(page_abstract) > len(result.get("abstract") or ""):
                result["abstract"] = page_abstract
            continue
        if page.get(key) and not result.get(key):
            result[key] = page[key]
    if result["abstract"] or (result["text"] and (page.get("looks_like_paper") or len(result["text"]) > 1500)):
        result["readable"] = True
        return result
    result["reason"] = "paywall" if page.get("looks_like_paper") else "not-paper"
    return result


def failure_line(paper):
    """读不到时的说法：直说读不到，不编内容。"""
    reason = (paper or {}).get("reason") or "no-network"
    line = REASON_LINES.get(reason, REASON_LINES["no-network"])
    title = ((paper or {}).get("title") or "").strip()
    if title and reason in ("paywall", "title-only", "blocked"):
        line = "这篇的题名是《%s》。%s" % (title, line)
    return line
