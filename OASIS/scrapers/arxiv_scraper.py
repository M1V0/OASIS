# ArXiv scraping logic (HTML parsing of search results)
import time
import logging
import httpx
from bs4 import BeautifulSoup

from ..config import ARXIV_PAGE_SIZE, ARXIV_HEADERS, ARXIV_SORT_ORDER
from ..utils import safe_request

def extract_text(soup, selector):
    try:
        return soup.select_one(selector).get_text(strip=True)
    except Exception:
        return None

def find_data(soup):
    for p in soup.select("p"):
        txt = p.get_text(strip=True)
        if txt.startswith("Submitted"):
            parts = txt.split(";")
            sub = parts[0].replace("Submitted", "").strip()
            ann = parts[-1].replace("originally announced", "").strip()
            return sub, ann
    return None, None

def parse_arxiv_page(content):
    soup = BeautifulSoup(content, "lxml")
    lis = soup.select("li.arxiv-result")
    results = []
    for li in lis:
        arxiv_id = None
        link = li.find("p", class_="list-title")
        if link:
            a_tag = link.find("a")
            if a_tag and "href" in a_tag.attrs:
                arxiv_id = a_tag["href"].split("/")[-1]

        title = extract_text(li, "p.title")
        authors = ",".join([a.get_text(strip=True) for a in li.select("p.authors > a")])
        abstract = extract_text(li, "span.abstract-full")
        if abstract:
            abstract = abstract.removesuffix("△ Less")
        comments = extract_text(li, "p.comments > span:nth-of-type(2)")
        sub, ann = find_data(li)

        results.append({
            "ID": arxiv_id,
            "Title": title,
            "Authors": authors,
            "Abstract": abstract,
            "Comments": comments,
            "Submitted": sub,
            "Announce": ann,
            "Provider": "ArXiv"
        })
    return results

def scrape_arxiv(url, feedback_callback=None, progress_callback=None, politeness="Normal"):
    client = httpx.Client(headers=ARXIV_HEADERS, timeout=30.0)
    all_results = {}
    page = 0

    politeness_delay = POLITENESS_CONFIG = None
    try:
        # POLITENESS_CONFIG imported lazily to avoid circular
        from config import POLITENESS_CONFIG
        politeness_delay = POLITENESS_CONFIG.get(politeness, POLITENESS_CONFIG["Normal"])["arxiv_delay"]
        retries = POLITENESS_CONFIG.get(politeness, POLITENESS_CONFIG["Normal"])["retries"]
    except Exception:
        politeness_delay = 1
        retries = 3

    while True:
        page_url = f"{url}&start={page * ARXIV_PAGE_SIZE}"
        msg = f"Fetching ArXiv page {page + 1}..."
        if feedback_callback:
            feedback_callback.emit(msg)

        res = safe_request("GET", page_url, client=client, retries=retries, backoff_factor=2, politeness_delay=politeness_delay, timeout=15)
        page_results = parse_arxiv_page(res.content)

        if not page_results:
            break

        for r in page_results:
            if r["ID"]:
                all_results[r["ID"]] = r

        if progress_callback:
            progress_callback.emit(min((page + 1) * 5, 100))

        page += 1
        if len(page_results) < ARXIV_PAGE_SIZE:
            break

    if progress_callback:
        progress_callback.emit(100)

    return list(all_results.values())
