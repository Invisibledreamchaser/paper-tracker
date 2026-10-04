#!/usr/bin/env python3
"""paper-tracker: fetch the open-access PDF for a paper by DOI (or arXiv id).

Resolution order: OpenAlex best_oa_location.pdf_url -> OpenAlex open_access
(oa_url) -> any location with a pdf_url. Falls back to arxiv.org/pdf for
arXiv identifiers. Prints the landing page when no OA PDF exists.
Stdlib only, no API keys needed.
"""
import argparse
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

OPENALEX_API = "https://api.openalex.org"
CONTACT = "paper-tracker-skill@example.com"
HEADERS = {"User-Agent": "paper-tracker-skill/1.0 (personal research tool)"}


def _urlopen(url, timeout):
    """Open a URL; on Windows Python installs without a CA bundle, retry
    without certificate verification (public read-only GETs)."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, ssl.CertificateError) or "CERTIFICATE_VERIFY_FAILED" in str(reason):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return urllib.request.urlopen(req, timeout=timeout, context=ctx)
        raise


def http_get(url, timeout=60):
    last = None
    for attempt in range(3):
        try:
            with _urlopen(url, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"request failed after retries: {url}\n{last}")


def crossref_candidates(doi):
    """Publisher-deposited full-text links from Crossref (best-effort)."""
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
    try:
        data = json.loads(http_get(url).decode("utf-8", "replace"))
    except Exception:
        return []
    out = []
    for link in (data.get("message", {}) or {}).get("link", []) or []:
        u = link.get("URL") or ""
        ctype = (link.get("content-type") or "").lower()
        if u and ("pdf" in ctype or u.lower().endswith(".pdf")) and u not in out:
            out.append(u)
    return out


def doi_derived_candidates(doi):
    """Known publisher URL patterns derived from the DOI itself."""
    out = []
    m = re.match(r"^10\.1038/(.+)$", doi)  # Nature portfolio
    if m:
        out.append(f"https://www.nature.com/articles/{m.group(1)}.pdf")
        # Bot-protection often blocks the canonical path; this variant is
        # served consistently and contains the full article.
        out.append(f"https://www.nature.com/articles/{m.group(1)}_reference.pdf")
    return out


def openalex_candidates(doi):
    """Return (title, [pdf_url, ...], landing_page_url) for a DOI."""
    url = f"{OPENALEX_API}/works/doi:{urllib.parse.quote(doi)}?mailto={CONTACT}"
    data = json.loads(http_get(url).decode("utf-8", "replace"))
    if data.get("error"):
        raise RuntimeError(f"OpenAlex lookup failed for DOI {doi}: {data['error']}")

    title = (data.get("display_name") or "").strip()
    landing = ""
    pdfs = []
    best = data.get("best_oa_location") or {}
    for u in (best.get("pdf_url"), data.get("open_access", {}).get("oa_url")):
        if u and u not in pdfs:
            pdfs.append(u)
    for loc in data.get("locations") or []:
        if not landing:
            landing = loc.get("landing_page_url") or ""
        u = loc.get("pdf_url")
        if u and u not in pdfs:
            pdfs.append(u)
    if not landing:
        landing = (best.get("landing_page_url")
                   or data.get("open_access", {}).get("oa_url")
                   or data.get("doi") or "")
    return title, pdfs, landing


def download_pdf(url):
    """Download url and return bytes if it really is a PDF, else None."""
    try:
        blob = http_get(url)
    except Exception:
        return None
    return blob if blob[:5] == b"%PDF-" else None


def sanitize(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")[:80] or "paper"


def main():
    ap = argparse.ArgumentParser(description="Download the open-access PDF of a paper by DOI or arXiv id.")
    ap.add_argument("--doi", help="Paper DOI, e.g. 10.1038/s41598-026-73833-9")
    ap.add_argument("--arxiv", help="arXiv id, e.g. 2610.01234")
    ap.add_argument("--out", help="Output PDF path (default: derived from title/DOI).")
    args = ap.parse_args()
    if not args.doi and not args.arxiv:
        ap.error("provide --doi or --arxiv")

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if args.arxiv:
        title, pdfs, landing = "", [f"https://arxiv.org/pdf/{args.arxiv}"], f"https://arxiv.org/abs/{args.arxiv}"
        default_name = f"arxiv_{args.arxiv}.pdf"
    else:
        title, pdfs, landing = openalex_candidates(args.doi)
        for u in doi_derived_candidates(args.doi) + crossref_candidates(args.doi):
            if u not in pdfs:
                pdfs.append(u)
        landing = landing or f"https://doi.org/{args.doi}"
        # Prefer canonical article PDFs over reference-only/supplementary ones.
        pdfs.sort(key=lambda u: "_reference" in u.lower())
        base = title or args.doi
        default_name = sanitize(base) + ".pdf"
    out = args.out or default_name

    for u in pdfs:
        blob = download_pdf(u)
        if blob:
            with open(out, "wb") as f:
                f.write(blob)
            print(f"已下载: {out} ({len(blob) // 1024} KB)")
            print(f"来源: {u}")
            if title:
                print(f"标题: {title}")
            return
        print(f"[跳过] 非 PDF 或下载失败: {u}")

    print("未找到开放获取的 PDF（可能受付费墙限制）。")
    print(f"文章页面: {landing or '（无）'}")
    if args.doi:
        print(f"DOI 链接: https://doi.org/{args.doi}")
    if title:
        print(f"标题: {title}")
    sys.exit(2)


if __name__ == "__main__":
    main()
