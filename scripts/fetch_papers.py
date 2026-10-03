#!/usr/bin/env python3
"""paper-tracker: fetch recent papers from arXiv and PubMed.

Queries both sources with one English boolean query, groups results
(arXiv by primary category, PubMed by journal) and writes a grouped
markdown draft for the model to turn into the final report.

Stdlib only — no third-party dependencies, no API keys needed.
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
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import date, timedelta

ARXIV_API = "https://export.arxiv.org/api/query"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OPENALEX_API = "https://api.openalex.org/works"
OPENALEX_CONTACT = "paper-tracker-skill@example.com"  # OpenAlex polite-pool contact
HEADERS = {"User-Agent": "paper-tracker-skill/1.0 (personal research tool)"}

ATOM = "{http://www.w3.org/2005/Atom}"
ARX = "{http://arxiv.org/schemas/atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"

ABSTRACT_LIMIT = 1200


def _urlopen(url, timeout):
    """Open a URL; on Windows Python installs without a CA bundle, retry
    without certificate verification (both APIs are public read-only GETs)."""
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


def http_get(url):
    last = None
    for attempt in range(3):
        try:
            with _urlopen(url, timeout=60) as resp:
                return resp.read()
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"request failed after retries: {url}\n{last}")


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def norm_title(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())[:80]


def date_window(args):
    end = date.fromisoformat(args.end) if args.end else date.today()
    start = date.fromisoformat(args.start) if args.start else end - timedelta(days=args.days - 1)
    return start, end


# ---------------------------------------------------------------- arXiv

def fetch_arxiv(query, cats, start, end, max_results):
    parts = []
    if cats:
        cat_q = " OR ".join(f"cat:{c.strip()}" for c in cats.split(",") if c.strip())
        if cat_q:
            parts.append(f"({cat_q})")
    parts.append(f"({query})")
    lo = start.strftime("%Y%m%d") + "0000"
    hi = end.strftime("%Y%m%d") + "2359"
    parts.append(f"submittedDate:[{lo} TO {hi}]")

    params = {
        "search_query": " AND ".join(parts),
        "start": "0",
        "max_results": str(max_results),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    xml_text = http_get(ARXIV_API + "?" + urllib.parse.urlencode(params)).decode("utf-8", "replace")
    root = ET.fromstring(xml_text)
    total = root.findtext(f"{OPENSEARCH}totalResults", "0")

    papers = []
    for e in root.findall(f"{ATOM}entry"):
        title = clean(e.findtext(f"{ATOM}title"))
        if not title or title.lower() == "error":
            continue
        aid = clean(e.findtext(f"{ATOM}id"))
        arxiv_id = re.sub(r"^.*?/abs/", "", aid)
        primary = ""
        pe = e.find(f"{ARX}primary_category")
        if pe is not None:
            primary = pe.get("term", "")
        papers.append({
            "title": title,
            "authors": [clean(a.findtext(f"{ATOM}name")) for a in e.findall(f"{ATOM}author")],
            "date": clean(e.findtext(f"{ATOM}published"))[:10],
            "updated": clean(e.findtext(f"{ATOM}updated"))[:10],
            "arxiv_id": arxiv_id,
            "primary_category": primary,
            "categories": [c.get("term", "") for c in e.findall(f"{ATOM}category")],
            "journal_ref": clean(e.findtext(f"{ARX}journal_ref")),
            "url": f"https://arxiv.org/abs/{arxiv_id}",
            "abstract": clean(e.findtext(f"{ATOM}summary"))[:ABSTRACT_LIMIT],
        })
    return papers, int(total or 0)


# ---------------------------------------------------------------- PubMed

def fetch_pubmed(query, start, end, max_results):
    params = {
        "db": "pubmed",
        "term": query,
        "mindate": start.strftime("%Y/%m/%d"),
        "maxdate": end.strftime("%Y/%m/%d"),
        "datetype": "pdat",
        "retmax": str(max_results),
        "retmode": "json",
        "sort": "date",
    }
    raw = http_get(EUTILS + "/esearch.fcgi?" + urllib.parse.urlencode(params)).decode("utf-8", "replace")
    res = json.loads(raw).get("esearchresult", {})
    ids = res.get("idlist", [])
    total = int(res.get("count", "0") or 0)
    time.sleep(0.4)
    if not ids:
        return [], total

    papers = OrderedDict()
    for i in range(0, len(ids), 40):
        batch = ids[i:i + 40]
        p = {"db": "pubmed", "id": ",".join(batch), "retmode": "json"}
        data = json.loads(http_get(EUTILS + "/esummary.fcgi?" + urllib.parse.urlencode(p)).decode("utf-8", "replace"))
        for uid, item in data.get("result", {}).items():
            if uid == "uids" or not isinstance(item, dict):
                continue
            authors = [a.get("name", "") for a in item.get("authors", []) if a.get("authtype") != "Collective"]
            doi = ""
            for artid in item.get("articleids", []):
                if artid.get("idtype") == "doi":
                    doi = artid.get("value", "")
                    break
            papers[uid] = {
                "pmid": uid,
                "title": clean(item.get("title", "")),
                "authors": authors,
                "journal": clean(item.get("fulljournalname", "")) or clean(item.get("source", "")) or "Unknown Journal",
                "journal_abbrev": clean(item.get("source", "")),
                "pubdate": clean(item.get("pubdate", "")),
                "sortdate": clean(item.get("sortdate", "")),
                "doi": doi,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
            }
        time.sleep(0.4)

    for i in range(0, len(ids), 20):
        batch = ids[i:i + 20]
        p = {"db": "pubmed", "id": ",".join(batch), "rettype": "abstract", "retmode": "xml"}
        xml_text = http_get(EUTILS + "/efetch.fcgi?" + urllib.parse.urlencode(p)).decode("utf-8", "replace")
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            time.sleep(0.4)
            continue
        for art in root.findall(".//PubmedArticle"):
            pmid = (art.findtext("MedlineCitation/PMID") or "").strip()
            if pmid not in papers:
                continue
            texts = []
            for at in art.findall(".//Abstract/AbstractText"):
                label = at.get("Label")
                t = clean("".join(at.itertext()))
                texts.append(f"{label}: {t}" if label else t)
            papers[pmid]["abstract"] = " ".join(texts)[:ABSTRACT_LIMIT]
        time.sleep(0.4)

    out = [papers[i] for i in ids if i in papers]
    out.sort(key=lambda x: x.get("sortdate", ""), reverse=True)
    return out, total


# ---------------------------------------------------------------- OpenAlex

def _openalex_terms(query):
    """OpenAlex search is AND across words; use the pipe operator to get OR
    (union) semantics over quoted phrases and bare words, and drop the
    arXiv/PubMed-style boolean operator tokens."""
    phrases = re.findall(r'"([^"]*)"', query)
    rest = re.sub(r'"[^"]*"', " ", query)
    words = [w for w in re.split(r"\s+", rest)
             if w and w.upper() not in ("AND", "OR", "ANDNOT", "NOT")]
    terms = [t.replace(",", " ").strip() for t in phrases + words]
    return "|".join(t for t in terms if t)


def _openalex_abstract(inv):
    if not inv:
        return ""
    positions = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return clean(" ".join(w for _, w in positions))[:ABSTRACT_LIMIT]


def fetch_openalex(query, start, end, max_results, journals=""):
    """Fetch journal articles from ALL publishers (IEEE, Elsevier, Springer,
    Wiley, MDPI, ACM, ...) via the OpenAlex aggregation API."""
    terms = _openalex_terms(query)
    if not terms:
        return [], 0
    filters = [
        f"title_and_abstract.search:{terms}",
        f"from_publication_date:{start.isoformat()}",
        f"to_publication_date:{end.isoformat()}",
        # OpenAlex's 2024 type taxonomy merged "journal-article" into "article"
        "type:article",
    ]
    journal_or = "|".join(j.strip() for j in journals.split(",") if j.strip())
    if journal_or:
        filters.append(f"primary_location.source.display_name.search:{journal_or}")
    params = {
        "filter": ",".join(filters),
        # Relevance sort: with OR terms the window can hold hundreds of loose
        # matches, so rank multi-term matches above single-term noise; the
        # date filters already constrain everything to the requested window.
        "sort": "relevance_score:desc",
        "per-page": str(min(max_results * 2, 200)),
        "mailto": OPENALEX_CONTACT,
        "select": "id,doi,display_name,publication_date,authorships,"
                  "primary_location,abstract_inverted_index",
    }
    data = json.loads(http_get(OPENALEX_API + "?" + urllib.parse.urlencode(params)).decode("utf-8", "replace"))
    total = int(data.get("meta", {}).get("count", 0) or 0)

    papers = []
    for w in data.get("results", []):
        title = clean(w.get("display_name") or "")
        if not title:
            continue
        source = (w.get("primary_location") or {}).get("source") or {}
        # Keep real journals; drop repository/directory deposits (Zenodo,
        # DOAJ, university portals) that OpenAlex also indexes as articles.
        if (source.get("type") or "").lower() != "journal":
            continue
        doi = ""
        m = re.search(r"doi\.org/(10\.\S+)$", w.get("doi") or "")
        if m:
            doi = m.group(1)
        papers.append({
            "title": title,
            "authors": [clean(a.get("author", {}).get("display_name") or "")
                        for a in w.get("authorships", [])],
            "date": clean(w.get("publication_date") or ""),
            "journal": clean(source.get("display_name") or "") or "Unknown Venue",
            "doi": doi,
            "openalex_id": clean(w.get("id") or ""),
            "url": f"https://doi.org/{doi}" if doi else clean(w.get("id") or ""),
            "abstract": _openalex_abstract(w.get("abstract_inverted_index")),
        })
    return papers[:max_results], total


# ---------------------------------------------------------------- render

def group_by(items, keyfn):
    g = OrderedDict()
    for it in items:
        g.setdefault(keyfn(it), []).append(it)
    return sorted(g.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def render(args, start, end, arxiv_papers, arxiv_total, pubmed_papers, pubmed_total,
           openalex_papers, openalex_total, openalex_dropped):
    journal_titles = ({norm_title(p["title"]) for p in pubmed_papers}
                      | {norm_title(p["title"]) for p in openalex_papers})
    L = []
    L.append(f"# 论文检索草稿")
    L.append(f"- 检索式：`{args.query}`")
    L.append(f"- 时间窗口：{start.isoformat()} ~ {end.isoformat()}（共 {(end - start).days + 1} 天）")
    L.append(f"- PubMed 命中 {pubmed_total} 篇（展示 {len(pubmed_papers)}）；"
             f"OpenAlex 命中 {openalex_total} 篇（展示 {len(openalex_papers)}，"
             f"与 PubMed 去重移除 {openalex_dropped} 篇）；arXiv 命中 {arxiv_total} 篇（展示 {len(arxiv_papers)}）")
    L.append("")

    if pubmed_papers:
        L.append(f"## PubMed 期刊论文（共 {len(pubmed_papers)} 篇）")
        for journal, items in group_by(pubmed_papers, lambda p: p["journal"]):
            L.append(f"### {journal}（{len(items)} 篇）")
            for n, p in enumerate(items, 1):
                authors = ", ".join(p["authors"][:3]) + (" et al." if len(p["authors"]) > 3 else "")
                L.append(f"{n}. **{p['title']}**")
                L.append(f"   - 作者：{authors}")
                L.append(f"   - 期刊：{p['journal']} ({p['journal_abbrev']})｜发表：{p['pubdate']}｜PMID: {p['pmid']}")
                if p["doi"]:
                    L.append(f"   - DOI: {p['doi']}")
                L.append(f"   - 链接：{p['url']}")
                L.append(f"   - 摘要：{p.get('abstract') or '（未获取到摘要）'}")
            L.append("")

    if openalex_papers:
        L.append(f"## OpenAlex 期刊论文（IEEE / Elsevier / Springer / Wiley / MDPI / ACM 等全出版社，共 {len(openalex_papers)} 篇）")
        for journal, items in group_by(openalex_papers, lambda p: p["journal"]):
            L.append(f"### {journal}（{len(items)} 篇）")
            for n, p in enumerate(items, 1):
                authors = ", ".join(p["authors"][:3]) + (" et al." if len(p["authors"]) > 3 else "")
                L.append(f"{n}. **{p['title']}**")
                L.append(f"   - 作者：{authors}")
                L.append(f"   - 期刊：{p['journal']}｜发表：{p['date']}")
                if p["doi"]:
                    L.append(f"   - DOI: {p['doi']}")
                L.append(f"   - 链接：{p['url']}")
                L.append(f"   - 摘要：{p.get('abstract') or '（该出版社未开放摘要）'}")
            L.append("")

    if arxiv_papers:
        L.append(f"## arXiv 预印本（共 {len(arxiv_papers)} 篇，未经同行评审）")
        for cat, items in group_by(arxiv_papers, lambda p: p["primary_category"] or "unknown"):
            L.append(f"### {cat}（{len(items)} 篇）")
            for n, p in enumerate(items, 1):
                authors = ", ".join(p["authors"][:3]) + (" et al." if len(p["authors"]) > 3 else "")
                flag = ""
                if norm_title(p["title"]) in journal_titles:
                    flag = " ⚠️（疑似已有期刊/PubMed 同名论文，可能为预印本版本）"
                L.append(f"{n}. **{p['title']}**{flag}")
                L.append(f"   - 作者：{authors}")
                L.append(f"   - 提交：{p['date']}" + (f"（最近更新 {p['updated']}）" if p["updated"] != p["date"] else ""))
                L.append(f"   - 分类：{', '.join(p['categories'][:4])}")
                if p["journal_ref"]:
                    L.append(f"   - 期刊引用：{p['journal_ref']}")
                L.append(f"   - 链接：{p['url']}")
                L.append(f"   - 摘要：{p.get('abstract') or '（未获取到摘要）'}")
            L.append("")

    if not pubmed_papers and not openalex_papers and not arxiv_papers:
        L.append("（三个来源均无命中结果）")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Fetch recent papers from arXiv, PubMed and OpenAlex.")
    ap.add_argument("--query", required=True,
                    help="English boolean query, e.g. '\"medical image\" AND (reconstruction OR \"2D to 3D\")'. "
                         "Boolean operators must be UPPERCASE for arXiv.")
    ap.add_argument("--days", type=int, default=7, help="Window length in days, ending today (default 7).")
    ap.add_argument("--start", help="Override window start, ISO date (YYYY-MM-DD).")
    ap.add_argument("--end", help="Override window end, ISO date (YYYY-MM-DD). Default today.")
    ap.add_argument("--arxiv-cats", default="", help="Comma-separated arXiv categories, e.g. cs.CV,eess.IV.")
    ap.add_argument("--openalex-journals", default="",
                    help="Optional comma-separated journal name filters for OpenAlex, e.g. "
                         "'IEEE Transactions on Medical Imaging,Medical Image Analysis'.")
    ap.add_argument("--sources", choices=["all", "both", "arxiv", "pubmed", "openalex"],
                    default="all", help="'both' is kept as an alias of 'all'.")
    ap.add_argument("--max", type=int, default=50, help="Max results per source (default 50).")
    ap.add_argument("--out", default="paper_draft.md", help="Output draft markdown path.")
    args = ap.parse_args()
    if args.sources == "both":
        args.sources = "all"

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    start, end = date_window(args)
    errors = []

    arxiv_papers, arxiv_total = [], 0
    if args.sources in ("all", "arxiv"):
        try:
            arxiv_papers, arxiv_total = fetch_arxiv(args.query, args.arxiv_cats, start, end, args.max)
        except Exception as e:
            errors.append(f"arXiv error: {e}")

    pubmed_papers, pubmed_total = [], 0
    if args.sources in ("all", "pubmed"):
        try:
            pubmed_papers, pubmed_total = fetch_pubmed(args.query, start, end, args.max)
        except Exception as e:
            errors.append(f"PubMed error: {e}")

    openalex_papers, openalex_total, openalex_dropped = [], 0, 0
    if args.sources in ("all", "openalex"):
        try:
            openalex_papers, openalex_total = fetch_openalex(
                args.query, start, end, args.max, args.openalex_journals)
            # Drop OpenAlex entries already present in PubMed (same journal
            # paper indexed twice); match by DOI first, then by title.
            pub_dois = {p["doi"].lower() for p in pubmed_papers if p.get("doi")}
            pub_titles = {norm_title(p["title"]) for p in pubmed_papers}
            kept = []
            for p in openalex_papers:
                if (p.get("doi") and p["doi"].lower() in pub_dois) \
                        or norm_title(p["title"]) in pub_titles:
                    openalex_dropped += 1
                else:
                    kept.append(p)
            openalex_papers = kept
        except Exception as e:
            errors.append(f"OpenAlex error: {e}")

    draft = render(args, start, end, arxiv_papers, arxiv_total, pubmed_papers, pubmed_total,
                   openalex_papers, openalex_total, openalex_dropped)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(draft)

    print(f"窗口: {start.isoformat()} ~ {end.isoformat()}")
    print(f"PubMed: 命中 {pubmed_total}，展示 {len(pubmed_papers)}")
    for journal, items in group_by(pubmed_papers, lambda p: p["journal"]):
        print(f"  - {journal}: {len(items)}")
    print(f"OpenAlex: 命中 {openalex_total}，展示 {len(openalex_papers)}（与 PubMed 去重移除 {openalex_dropped}）")
    for journal, items in group_by(openalex_papers, lambda p: p["journal"]):
        print(f"  - {journal}: {len(items)}")
    print(f"arXiv: 命中 {arxiv_total}，展示 {len(arxiv_papers)}")
    for cat, items in group_by(arxiv_papers, lambda p: p["primary_category"] or "unknown"):
        print(f"  - {cat}: {len(items)}")
    print(f"草稿已写入: {args.out}")
    for err in errors:
        print(f"[警告] {err}")
    if not pubmed_papers and not openalex_papers and not arxiv_papers and not errors:
        print("提示：无结果时尝试放宽检索式（减少 AND 限定、增加同义词），"
              "确认布尔运算符为全大写 AND/OR/ANDNOT，短语用英文双引号，或加大 --days。")


if __name__ == "__main__":
    main()
