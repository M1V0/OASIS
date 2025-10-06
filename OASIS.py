"""
OASIS - Open ArXiv Scraper for Implementing Systematic Reviews
"""

import os
import re
import sys
import time
import random
import logging
import webbrowser
from datetime import datetime

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox,
    QRadioButton, QButtonGroup, QMessageBox, QGroupBox,
    QTabWidget, QFrame, QGridLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QIcon, QMovie

# ----------------- Constants -----------------
ARXIV_PAGE_SIZE = 200
ARXIV_SORT_ORDER = "-announced_date_first"
ARXIV_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/106.0.0.0 Safari/537.36"
}

OSF_PAGE_SIZE = 100
OSF_API_BASE = "https://api.osf.io/v2/preprints/"
OSF_ELASTIC_URL = "https://share.osf.io/api/v2/search/creativeworks/_search"

SERVERS = {
    "ArXiv": {
        "type": "arxiv",
        "display_name": "ArXiv",
        "fields": ["all", "title", "abstract", "author"],
        "operators": ["AND", "OR"]
    },
    "PsyArXiv": {"type": "osf", "display_name": "PsyArXiv", "provider": "psyarxiv"},
    "SocArXiv": {"type": "osf", "display_name": "SocArXiv", "provider": "socarxiv"},
    "engrXiv": {"type": "osf", "display_name": "engrXiv", "provider": "engrxiv"},
    "LawArXiv": {"type": "osf", "display_name": "LawArXiv", "provider": "lawarxiv"},
    "MedArXiv": {"type": "osf", "display_name": "MedArXiv", "provider": "medrxiv"},
    "ECSarXiv": {"type": "osf", "display_name": "ECSarXiv", "provider": "ecsarxiv"},
    "Thesis Commons": {"type": "osf", "display_name": "Thesis Commons", "provider": "thesiscommons"},
}

OSF_PROVIDERS = {
    "psyarxiv": "PsyArXiv",
    "socarxiv": "SocArXiv",
    "engrxiv": "engrXiv",
    "lawarxiv": "LawArXiv",
    "medrxiv": "MedArXiv",
    "ecsarxiv": "ECSarXiv",
    "thesiscommons": "Thesis Commons"
}

POLITENESS_CONFIG = {
    "Fast": {"osf_delay": 0.0, "arxiv_delay": 0.5, "retries": 2},
    "Normal": {"osf_delay": 0.5, "arxiv_delay": 3.0, "retries": 4},
    "Slow": {"osf_delay": 1.0, "arxiv_delay": 5.0, "retries": 6},
}

# ----------------- Safe request helper -----------------


def safe_request(method, url, client=None, retries=4, backoff_factor=2, politeness_delay=0.5, **kwargs):
    """
    Perform an HTTP request with retry/backoff for 429 and basic RequestError handling.
    - method: "GET"/"POST"
    - client: httpx.Client instance (optional)
    - retries: number of retry attempts
    - backoff_factor: base for exponential backoff
    - politeness_delay: a delay after a successful request (seconds)
    - kwargs forwarded to client.request()
    """
    attempt = 0
    while True:
        try:
            if client is not None:
                res = client.request(method, url, **kwargs)
            else:
                res = httpx.request(method, url, **kwargs)

            # If we hit a rate limit, back off + jitter and retry
            if res.status_code == 429:
                wait = (backoff_factor ** attempt) + random.uniform(0, 1)
                logging.warning(f"429 received for {url}. Backing off {wait:.1f}s (attempt {attempt + 1}/{retries}).")
                time.sleep(wait)
                attempt += 1
                if attempt >= retries:
                    res.raise_for_status()  # surface the 429 after exhausting retries
                continue

            res.raise_for_status()

            # politeness delay after successful request
            if politeness_delay and politeness_delay > 0:
                time.sleep(politeness_delay)

            return res

        except httpx.RequestError as e:
            # network-level failure
            wait = (backoff_factor ** attempt) + random.uniform(0, 1)
            logging.warning(f"Request error: {e}. Retrying in {wait:.1f}s (attempt {attempt + 1}/{retries}).")
            time.sleep(wait)
            attempt += 1
            if attempt >= retries:
                raise


# ----------------- ArXiv scraping -----------------


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

    politeness_delay = POLITENESS_CONFIG.get(politeness, POLITENESS_CONFIG["Normal"])["arxiv_delay"]
    retries = POLITENESS_CONFIG.get(politeness, POLITENESS_CONFIG["Normal"])["retries"]

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


# ----------------- OSF functions -----------------


class OSFPreprints:
    def __init__(self, provider="psyarxiv", politeness="Normal"):
        self.provider = provider
        self.API = OSF_API_BASE
        self.client = httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=30.0)
        self.results = []
        self.abort_flag = False
        self.politeness = politeness

    def build_params(self, query=None, page=1):
        params = {
            "filter[provider]": self.provider,
            "page[size]": OSF_PAGE_SIZE,
            "page[number]": page,
        }
        if query:
            params["filter[title][icontains]"] = str(query).strip()
        return params

    def fetch_page(self, query, page=1):
        if self.abort_flag:
            return None
        params = self.build_params(query=query, page=page)
        politeness_delay = POLITENESS_CONFIG.get(self.politeness, POLITENESS_CONFIG["Normal"])["osf_delay"]
        retries = POLITENESS_CONFIG.get(self.politeness, POLITENESS_CONFIG["Normal"])["retries"]

        res = safe_request("GET", self.API, client=self.client, params=params, retries=retries, backoff_factor=2, politeness_delay=politeness_delay)
        return res.json()

    def run(self, query, progress_callback=None):
        self.results = []
        page = 1
        while True:
            if self.abort_flag:
                break
            data = self.fetch_page(query, page)
            if data is None:
                break

            for item in data.get("data", []):
                if self.abort_flag:
                    break
                attrs = item.get("attributes", {}) or {}
                tags = attrs.get("tags", []) if isinstance(attrs.get("tags", []), list) else []
                self.results.append({
                    "ID": item.get("id", ""),
                    "Title": attrs.get("title", "") or "",
                    "Abstract": attrs.get("description", "") or "",
                    "Date Published": attrs.get("date_published", "") or "",
                    "Tags": ",".join([t if isinstance(t, str) else str(t) for t in tags]),
                    "DOI": attrs.get("doi", "") or "",
                    "URL": item.get("links", {}).get("html", "") or "",
                    "Contributors": "",
                    "Provider": self.provider,
                })

            if progress_callback:
                progress_callback.emit(f"Fetched page {page}, {len(self.results)} results so far...")
            links = data.get("links", {}) or {}
            if not links.get("next") or self.abort_flag:
                break
            page += 1

        df = pd.DataFrame(self.results)
        if "ID" not in df.columns:
            df["ID"] = ""
        return df.drop_duplicates(subset="ID")


class ElasticPreprints:
    def __init__(self, provider="psyarxiv", politeness="Normal"):
        self.provider = provider
        self.client = httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=30.0)
        self.abort_flag = False
        self.politeness = politeness

    def normalize_query(self, query: str) -> str:
        if not query:
            return query
        # Replace symbol operators
        query = query.replace("|", " OR ").replace("&", " AND ")
        # Normalize words to uppercase boolean operators
        query = re.sub(r"\band\b", "AND", query, flags=re.IGNORECASE)
        query = re.sub(r"\bor\b", "OR", query, flags=re.IGNORECASE)
        query = re.sub(r"\bnot\b", "NOT", query, flags=re.IGNORECASE)
        query = re.sub(r"\s+", " ", query).strip()
        return query

    def run(self, query, progress_callback=None):
        rows = []
        size = 200
        start = 0

        query = self.normalize_query(query)

        politeness_delay = POLITENESS_CONFIG.get(self.politeness, POLITENESS_CONFIG["Normal"])["osf_delay"]
        retries = POLITENESS_CONFIG.get(self.politeness, POLITENESS_CONFIG["Normal"])["retries"]

        while True:
            if self.abort_flag:
                break

            payload = {
                "query": {
                    "bool": {
                        "must": {
                            "query_string": {"query": query}
                        },
                        "filter": [
                            {"terms": {"sources": [OSF_PROVIDERS[self.provider]]}}
                        ]
                    }
                },
                "from": start,
                "size": size
            }

            res = safe_request("POST", OSF_ELASTIC_URL, client=self.client, json=payload, retries=retries, backoff_factor=2, politeness_delay=politeness_delay)
            data = res.json()
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break

            for h in hits:
                if self.abort_flag:
                    break
                s = h.get("_source", {})
                contributors = []
                lists_contribs = s.get("lists", {}).get("contributors", []) if isinstance(s.get("lists", {}).get("contributors", []), list) else []
                for c in lists_contribs:
                    name = c.get("name")
                    if name:
                        contributors.append(name)
                rows.append({
                    "ID": s.get("id", ""),
                    "Title": s.get("title", ""),
                    "Abstract": s.get("description", ""),
                    "Date Published": s.get("date_published", ""),
                    "Tags": ",".join(s.get("tags", []) if isinstance(s.get("tags", []), list) else []),
                    "DOI": s.get("doi", ""),
                    "URL": s.get("links", {}).get("html", ""),
                    "Contributors": ", ".join(contributors),
                    "Provider": self.provider,
                })

            if progress_callback:
                progress_callback.emit(f"Fetched {len(rows)} results so far...")

            start += size
            if len(hits) < size:
                break

        df = pd.DataFrame(rows)
        if "ID" not in df.columns:
            df["ID"] = ""
        return df.drop_duplicates(subset="ID")


# ----------------- Worker thread -----------------


class ScraperThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(pd.DataFrame)
    error = pyqtSignal(str)

    def __init__(self, server_config, query, search_mode, conditions=None, url=None, politeness="Normal"):
        super().__init__()
        self.server_config = server_config
        self.query = query
        self.search_mode = search_mode
        self.conditions = conditions
        self.url = url
        self.client = None
        self.abort_flag = False
        self.politeness = politeness

    def run(self):
        try:
            if self.server_config["type"] == "arxiv":
                if self.url:
                    final_url = self.url
                else:
                    # build ArXiv URL from conditions (re-implement minimal builder)
                    terms_list = []
                    first_operator = self.conditions[0]['operator'] if self.conditions else "AND"
                    for cond in (self.conditions or []):
                        val = cond['value'].strip()
                        if val:
                            if not (val.startswith('"') and val.endswith('"')):
                                val = f'"{val}"'
                            terms_list.append(val)
                    terms_str = f" {first_operator} ".join(terms_list)
                    terms_encoded = terms_str.replace(" ", "+")
                    final_url = (
                        f"https://arxiv.org/search/advanced?advanced="
                        f"&terms-0-operator={first_operator}"
                        f"&terms-0-term={terms_encoded}"
                        f"&terms-0-field={self.conditions[0]['field'] if self.conditions else 'all'}"
                        f"&classification-physics_archives=all"
                        f"&classification-include_cross_list=include"
                        f"&date-filter_by=all_dates"
                        f"&date-year=&date-from_date=&date-to_date="
                        f"&date-date_type=submitted_date"
                        f"&abstracts=show"
                        f"&size={ARXIV_PAGE_SIZE}"
                        f"&order={ARXIV_SORT_ORDER}"
                    )

                self.progress.emit(f"Starting ArXiv scrape using query: {self.query or 'ArXiv build/paste'}")
                # Log the exact url & note query
                logging.info(f"ArXiv scrape started. URL: {final_url}")
                logging.info(f"using query: {self.query}")
                results = scrape_arxiv(final_url, feedback_callback=self.progress, progress_callback=None, politeness=self.politeness)
                df = pd.DataFrame(results)

            else:
                provider = self.server_config["provider"]
                if self.search_mode == "api":
                    self.client = OSFPreprints(provider=provider, politeness=self.politeness)
                else:
                    self.client = ElasticPreprints(provider=provider, politeness=self.politeness)

                # Log the exact query we will use
                logging.info(f"OSF scrape started on provider={provider}")
                logging.info(f"using query: {self.query}")

                self.progress.emit(f"Starting OSF scrape using query: {self.query}")
                df = self.client.run(self.query, progress_callback=self.progress)

            self.finished.emit(df)
        except Exception as e:
            self.error.emit(str(e))

    def abort(self):
        self.abort_flag = True
        if self.client:
            self.client.abort_flag = True


# ----------------- InfoLabel -----------------


class InfoLabel(QLabel):
    def __init__(self, tooltip_text=""):
        super().__init__("?")
        self.setToolTip(tooltip_text)
        self.setStyleSheet("""
            QLabel {
                color: #0066cc;
                font-weight: bold;
                font-size: 11px;
                background-color: #e6f3ff;
                border: 1px solid #0066cc;
                border-radius: 8px;
                min-width: 16px;
                min-height: 16px;
                max-width: 16px;
                max-height: 16px;
                margin: 2px;
            }
            QLabel:hover { background-color: #cce7ff; color: #004499; }
        """)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


# ----------------- Main Window -----------------


class OASISScraperApp(QMainWindow):
    def __init__(self):
        super().__init__()

        # Ensure directories
        os.makedirs("data", exist_ok=True)
        os.makedirs("logs", exist_ok=True)

        # Logging (per-session file)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_filename = os.path.join("logs", f"OASIS_Log_{timestamp}.txt")
        logging.basicConfig(filename=self.log_filename,
                            level=logging.INFO,
                            format="%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
        logging.info("=== New OASIS session started ===")

        self.scraper_thread = None
        self.current_server = "ArXiv"

        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("OASIS - Open ArXiv Scraper for Implementing Systematic Reviews")
        self.setGeometry(100, 100, 710, 600)

        # central layout
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        #header layout
        header_layout = QHBoxLayout()
        
        # Logo
        self.logo_label = QLabel()
        pixmap = QPixmap("var/OASIS.png")
        
        # Scale the logo proportionally
        scaled_pixmap = pixmap.scaledToHeight(60, Qt.TransformationMode.SmoothTransformation)
        self.logo_label.setPixmap(scaled_pixmap)
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.logo_label.setToolTip("OASIS Preprint Scraper")
        
        # Title
        header = QLabel("OASIS — Open ArXiv Scraper for Implementing Systematic Reviews")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        
        # Add both to the horizontal layout
        header_layout.addWidget(self.logo_label)
        header_layout.addSpacing(10)  # small gap between logo and text
        header_layout.addWidget(header)
        header_layout.addStretch()  # push them to the left if you want
        
        # Then add that layout to your main (vertical) layout
        layout.addLayout(header_layout)
        

        # Config group (server, strategy, politeness)
        config_group = QGroupBox("Search Configuration")
        config_layout = QHBoxLayout()

        server_label = QLabel("Server:")
        server_info = InfoLabel("Choose which preprint server to search.")
        self.server_combo = QComboBox()
        self.server_combo.addItems(list(SERVERS.keys()))
        self.server_combo.setCurrentText("ArXiv")
        self.server_combo.currentTextChanged.connect(self.server_changed)

        # Strategy (for OSF only)
        self.strategy_label = QLabel("Strategy:")
        self.strategy_info = InfoLabel("OSF API: Official title-only search. Weblike: Elastic full-text-ish search.")
        self.strategy_group = QButtonGroup()
        self.standard_radio = QRadioButton("OSF API")
        self.comprehensive_radio = QRadioButton("Weblike API")
        self.standard_radio.setChecked(True)
        self.strategy_group.addButton(self.standard_radio)
        self.strategy_group.addButton(self.comprehensive_radio)

        # Politeness
        politeness_label = QLabel("Politeness:")
        politeness_info = InfoLabel("Choose request politeness. Normal = default, Fast = minimal delay, Slow = adds delays between requests.")
        self.politeness_combo = QComboBox()
        self.politeness_combo.addItems(list(POLITENESS_CONFIG.keys()))
        self.politeness_combo.setCurrentText("Normal")

        config_layout.addWidget(server_label)
        config_layout.addWidget(server_info)
        config_layout.addWidget(self.server_combo)
        config_layout.addSpacing(10)
        config_layout.addWidget(self.strategy_label)
        config_layout.addWidget(self.strategy_info)
        config_layout.addWidget(self.standard_radio)
        config_layout.addWidget(self.comprehensive_radio)
        config_layout.addStretch()
        config_layout.addWidget(politeness_label)
        config_layout.addWidget(politeness_info)
        config_layout.addWidget(self.politeness_combo)

        config_group.setLayout(config_layout)
        layout.addWidget(config_group)

        # Tabs: ArXiv Build, ArXiv Paste, OSF Query
        self.tabs = QTabWidget()
        self.arxiv_build_tab = QWidget()
        self.arxiv_paste_tab = QWidget()
        self.osf_tab = QWidget()
        self.tabs.addTab(self.arxiv_build_tab, "Build Query")
        self.tabs.addTab(self.arxiv_paste_tab, "Paste URL")
        self.tabs.addTab(self.osf_tab, "OSF Query")

        layout.addWidget(self.tabs)

        # ArXiv build tab content
        self.setup_arxiv_build_tab()

        # ArXiv paste tab content
        self.setup_arxiv_paste_tab()

        # OSF tab content
        self.setup_osf_tab()

        # Action area
        action_group = QGroupBox("Output & Actions")
        action_layout = QHBoxLayout()

        filename_label = QLabel("Filename base:")
        filename_info = InfoLabel("Base filename for CSV output. Server and mode appended.")
        self.filename_input = QLineEdit("OASIS_search")

        self.preview_button = QPushButton("Preview URL")
        self.preview_button.clicked.connect(self.preview_url)

        # Start Search button with spinner
        self.run_button = QPushButton("Start Search")
        self.run_button.setObjectName("runButton")
        self.run_button.clicked.connect(self.run_scraper)

        # Prepare spinner movie (external file expected at var/spinner.gif or var/spinner.gif fallback)
        gif_path = "var/spinner.gif"
        if not os.path.exists(gif_path):
            gif_path = "spinner.gif"  # allow alternative location
        try:
            self.spinner_movie = QMovie(gif_path)
            self.spinner_movie.setScaledSize(QSize(16, 16))
        except Exception:
            self.spinner_movie = None

        self.abort_button = QPushButton("Abort")
        self.abort_button.setObjectName("abortButton")
        self.abort_button.clicked.connect(self.abort_scraper)
        self.abort_button.setEnabled(False)

        action_layout.addWidget(filename_label)
        action_layout.addWidget(filename_info)
        action_layout.addWidget(self.filename_input)
        action_layout.addStretch()
        action_layout.addWidget(self.preview_button)
        action_layout.addWidget(self.run_button)
        action_layout.addWidget(self.abort_button)

        action_group.setLayout(action_layout)
        layout.addWidget(action_group)

        # Feedback/results area
        results_group = QGroupBox("Results Log")
        results_layout = QVBoxLayout()
        self.feedback_text = QTextEdit()
        self.feedback_text.setReadOnly(True)
        self.feedback_text.setMaximumHeight(200)
        results_layout.addWidget(self.feedback_text)
        results_group.setLayout(results_layout)
        layout.addWidget(results_group)

        # Footer (license, github, creator)
        footer = QFrame()
        footer_layout = QHBoxLayout(footer)
        license_label = QLabel('<a href="https://creativecommons.org/licenses/by/4.0/">CC-BY License</a>')
        license_label.setOpenExternalLinks(True)
        github_label = QLabel('<a href="https://github.com/M1V0/OASIS">GitHub</a>')
        github_label.setOpenExternalLinks(True)
        creator_label = QLabel("Created by Matthew Ivory")
        creator_label.setStyleSheet("color: gray; font-size: 11px;")

        footer_layout.addWidget(license_label)
        footer_layout.addSpacing(12)
        footer_layout.addWidget(github_label)
        footer_layout.addStretch()
        footer_layout.addWidget(creator_label)
        layout.addWidget(footer)

        # Set initial server UI state
        self.server_changed(self.server_combo.currentText())

    def setup_arxiv_build_tab(self):
        layout = QVBoxLayout(self.arxiv_build_tab)
        # condition builder: small grid
        cond_group = QGroupBox("Search Conditions")
        cond_layout = QVBoxLayout()

        self.condition_rows_widget = QWidget()
        self.condition_rows_layout = QGridLayout(self.condition_rows_widget)
        self.condition_rows_layout.addWidget(QLabel("#"), 0, 0)
        self.condition_rows_layout.addWidget(QLabel("Operator"), 0, 1)
        self.condition_rows_layout.addWidget(QLabel("Field"), 0, 2)
        self.condition_rows_layout.addWidget(QLabel("Search Term"), 0, 3)
        self.condition_rows_layout.setColumnStretch(3, 1)

        cond_layout.addWidget(self.condition_rows_widget)

        btn_layout = QHBoxLayout()
        self.add_condition_button = QPushButton("➕ Add Term")
        self.add_condition_button.clicked.connect(self.add_condition_row)
        self.remove_condition_button = QPushButton("➖ Remove Term")
        self.remove_condition_button.clicked.connect(self.remove_condition_row)
        btn_layout.addWidget(self.add_condition_button)
        btn_layout.addWidget(self.remove_condition_button)
        btn_layout.addStretch()
        cond_layout.addLayout(btn_layout)

        cond_group.setLayout(cond_layout)
        layout.addWidget(cond_group)

        self.condition_rows = []
        self.add_condition_row()

    def setup_arxiv_paste_tab(self):
        layout = QVBoxLayout(self.arxiv_paste_tab)
        group = QGroupBox("Paste ArXiv Advanced Search URL")
        g_l = QVBoxLayout()
        info = InfoLabel("Paste a complete ArXiv advanced search URL. The tool will optimise it for systematic extraction.")
        self.paste_url_text = QTextEdit()
        self.paste_url_text.setMaximumHeight(80)
        g_l.addWidget(info)
        g_l.addWidget(self.paste_url_text)
        group.setLayout(g_l)
        layout.addWidget(group)

    def setup_osf_tab(self):
        layout = QVBoxLayout(self.osf_tab)
        group = QGroupBox("OSF Search")
        g_l = QVBoxLayout()
        info = InfoLabel("Enter search terms. OSF API searches titles only; Weblike uses titles, abstracts, and keywords.")
        self.osf_query_input = QTextEdit()
        self.osf_query_input.setMaximumHeight(80)
        self.osf_query_input.setPlaceholderText("e.g. cognitive therapy AND depression")
        g_l.addWidget(info)
        g_l.addWidget(self.osf_query_input)
        group.setLayout(g_l)
        layout.addWidget(group)

    def add_condition_row(self):
        row_index = len(self.condition_rows) + 1
        op = QComboBox()
        op.addItems(["AND", "OR"])
        if len(self.condition_rows) == 0:
            op.setEnabled(False)
        field = QComboBox()
        field.addItems(SERVERS["ArXiv"]["fields"])
        value = QLineEdit()
        value.setPlaceholderText("Enter search term...")
        # add widgets
        self.condition_rows_layout.addWidget(QLabel(f"{len(self.condition_rows) + 1}."), row_index, 0)
        self.condition_rows_layout.addWidget(op, row_index, 1)
        self.condition_rows_layout.addWidget(field, row_index, 2)
        self.condition_rows_layout.addWidget(value, row_index, 3)
        self.condition_rows.append({"operator": op, "field": field, "value": value})

    def remove_condition_row(self):
        if not self.condition_rows:
            return
        last = self.condition_rows.pop()
        # delete widgets (simple approach)
        last["operator"].deleteLater()
        last["field"].deleteLater()
        last["value"].deleteLater()
        # remove the numbering label by searching for it
        for i in reversed(range(self.condition_rows_layout.count())):
            w = self.condition_rows_layout.itemAt(i).widget()
            if isinstance(w, QLabel) and w.text() == f"{len(self.condition_rows) + 1}.":
                w.deleteLater()
                break

    def server_changed(self, server_name):
        self.current_server = server_name
        server_config = SERVERS[server_name]
        if server_config["type"] == "arxiv":
            # hide OSF strategy widgets
            self.strategy_label.setVisible(False)
            self.strategy_info.setVisible(False)
            self.standard_radio.setVisible(False)
            self.comprehensive_radio.setVisible(False)
            # show arxiv tabs
            self.tabs.setTabVisible(0, True)
            self.tabs.setTabVisible(1, True)
            self.tabs.setTabVisible(2, False)
            self.tabs.setCurrentIndex(0)
            self.preview_button.setVisible(True)
        else:
            self.strategy_label.setVisible(True)
            self.strategy_info.setVisible(True)
            self.standard_radio.setVisible(True)
            self.comprehensive_radio.setVisible(True)
            self.tabs.setTabVisible(0, False)
            self.tabs.setTabVisible(1, False)
            self.tabs.setTabVisible(2, True)
            self.tabs.setCurrentIndex(2)
            self.preview_button.setVisible(False)

    # ---------- Utilities for filenames ----------
    @staticmethod
    def unique_filename(path):
        """
        If path exists, append _1, _2, ... before extension.
        """
        base, ext = os.path.splitext(path)
        counter = 1
        new = path
        while os.path.exists(new):
            new = f"{base}_{counter}{ext}"
            counter += 1
        return new

    # ---------- Main runner ----------
    def run_scraper(self):
        server_config = SERVERS[self.current_server]
        base_filename = self.filename_input.text().strip() or "OASIS_search"
        politeness = self.politeness_combo.currentText()

        # Clear feedback
        self.feedback_text.clear()

        # Start spinner inside button (if movie available)
        if self.spinner_movie:
            # ensure no duplicate connections
            try:
                self.spinner_movie.frameChanged.disconnect()
            except Exception:
                pass
            self.run_button.setEnabled(False)
            self.run_button.setText(" Searching...")
            if self.spinner_movie.currentPixmap() and not self.spinner_movie.currentPixmap().isNull():
                self.run_button.setIcon(QIcon(self.spinner_movie.currentPixmap()))
            self.spinner_movie.frameChanged.connect(lambda: self.run_button.setIcon(QIcon(self.spinner_movie.currentPixmap())))
            self.spinner_movie.start()
        else:
            self.run_button.setEnabled(False)
            self.run_button.setText(" Searching...")

        self.abort_button.setEnabled(True)

        try:
            # prepare thread args
            if server_config["type"] == "arxiv":
                # ArXiv mode
                if self.tabs.currentIndex() == 0:  # Build Query
                    conditions = []
                    for row in self.condition_rows:
                        field = row['field'].currentText()
                        operator = row['operator'].currentText() if row['operator'].isEnabled() else "AND"
                        value = row['value'].text().strip()
                        if value:
                            conditions.append({'field': field, 'operator': operator, 'value': value})
                    if not conditions:
                        QMessageBox.warning(self, "Input Error", "Add at least one search term.")
                        # reset button
                        self._reset_run_button()
                        return

                    # Log exact conditions (build string for log clarity)
                    constructed_terms = " ".join([f"{c['operator']} {c['value']}" if i != 0 else c['value']
                                                  for i, c in enumerate(conditions)])
                    logging.info(f"Starting ArXiv Build Query search (conditions: {constructed_terms})")
                    log_query_str = constructed_terms

                    self.scraper_thread = ScraperThread(
                        server_config=server_config,
                        query=log_query_str,
                        search_mode="build_query",
                        conditions=conditions,
                        url=None,
                        politeness=politeness
                    )

                else:  # Paste URL tab
                    url = self.paste_url_text.toPlainText().strip()
                    if not url:
                        QMessageBox.warning(self, "Input Error", "Please paste a valid ArXiv search URL.")
                        self._reset_run_button()
                        return
                    # Force size & order
                    url = re.sub(r"size=\d+", f"size={ARXIV_PAGE_SIZE}", url)
                    if "order=" in url:
                        url = re.sub(r"order=[^&]+", f"order={ARXIV_SORT_ORDER}", url)
                    else:
                        url += f"&order={ARXIV_SORT_ORDER}"
                    logging.info(f"Starting ArXiv Paste URL search. URL: {url}")
                    logging.info(f"using query: {url}")
                    self.scraper_thread = ScraperThread(
                        server_config=server_config,
                        query=url,
                        search_mode="paste_url",
                        conditions=None,
                        url=url,
                        politeness=politeness
                    )

            else:
                # OSF mode
                query = self.osf_query_input.toPlainText().strip()
                if not query:
                    QMessageBox.warning(self, "Input Error", "Please enter search terms.")
                    self._reset_run_button()
                    return
                search_mode = "api" if self.standard_radio.isChecked() else "weblike"
                logging.info(f"Starting OSF search on provider={self.current_server}, mode={search_mode}")
                logging.info(f"using query: {query}")
                self.scraper_thread = ScraperThread(
                    server_config=server_config,
                    query=query,
                    search_mode=search_mode,
                    politeness=politeness
                )

            # connect signals
            self.scraper_thread.progress.connect(self.update_progress)
            self.scraper_thread.finished.connect(self.scraper_finished)
            self.scraper_thread.error.connect(self.scraper_error)
            self.scraper_thread.start()

        except Exception as e:
            self.scraper_error(str(e))

    def _reset_run_button(self):
        """Reset run button UI and spinner."""
        if self.spinner_movie:
            try:
                self.spinner_movie.stop()
            except Exception:
                pass
            try:
                self.spinner_movie.frameChanged.disconnect()
            except Exception:
                pass
        self.run_button.setEnabled(True)
        self.run_button.setText("Start Search")
        self.run_button.setIcon(QIcon())
        self.abort_button.setEnabled(False)

    def abort_scraper(self):
        logging.warning(f"Search aborted on server={self.current_server}")
        if self.scraper_thread:
            self.feedback_text.append("\n⚠️ Aborting search...\n")
            self.scraper_thread.abort()
            self.abort_button.setEnabled(False)
        self._reset_run_button()

    def update_progress(self, message):
        # append message to feedback box and to log
        self.feedback_text.append(message)
        logging.info(message)

    def scraper_finished(self, df):
        # log completion
        logging.info(f"Search completed successfully on server={self.current_server}, results={len(df)}")

        # stop spinner and reset button
        self._reset_run_button()

        if df is None or df.empty:
            self.feedback_text.append("\n❌ No preprints found.\n")
            QMessageBox.warning(self, "No Results", "No preprints were found matching your criteria.")
            return

        base_filename = self.filename_input.text().strip() or "OASIS_search"
        server_name = self.current_server

        if SERVERS[server_name]["type"] == "arxiv":
            filename = os.path.join("data", f"{base_filename}_{server_name}.csv")
        else:
            search_mode = "OSF_API" if self.standard_radio.isChecked() else "weblike"
            filename = os.path.join("data", f"{base_filename}_{server_name}_{search_mode}.csv")

        unique = self.unique_filename(filename)
        df.to_csv(unique, index=False)

        msg = f"\nSearch complete. {len(df)} preprints saved to '{unique}'"
        self.feedback_text.append(msg)
        logging.info(msg)
        QMessageBox.information(self, "Search Complete", f"Successfully collected {len(df)} preprints.\n\nFile saved as: {unique}\nLog file: {self.log_filename}")

    def scraper_error(self, error_msg):
        logging.error(f"Search failed on server={self.current_server}, error={error_msg}")
        self.feedback_text.append(f"\n Error: {error_msg}\n")
        QMessageBox.critical(self, "Search Error", f"An error occurred:\n{error_msg}")
        self._reset_run_button()

    def preview_url(self):
        # Only works in ArXiv Build Query
        if self.current_server != "ArXiv" or self.tabs.currentIndex() != 0:
            QMessageBox.information(self, "Preview URL", "URL preview works only in ArXiv Build Query mode.")
            return
        conditions = []
        for row in self.condition_rows:
            field = row['field'].currentText()
            operator = row['operator'].currentText() if row['operator'].isEnabled() else "AND"
            value = row['value'].text().strip()
            if value:
                conditions.append({'field': field, 'operator': operator, 'value': value})
        if not conditions:
            QMessageBox.warning(self, "Preview URL", "Add at least one search term first.")
            return
        # Build same way ScraperThread does for build
        first_operator = conditions[0]['operator']
        terms_list = []
        for cond in conditions:
            val = cond['value'].strip()
            if val:
                if not (val.startswith('"') and val.endswith('"')):
                    val = f'"{val}"'
                terms_list.append(val)
        terms_str = f" {first_operator} ".join(terms_list)
        terms_encoded = terms_str.replace(" ", "+")
        url = (
            f"https://arxiv.org/search/advanced?advanced="
            f"&terms-0-operator={first_operator}"
            f"&terms-0-term={terms_encoded}"
            f"&terms-0-field={conditions[0]['field'] if conditions else 'all'}"
            f"&classification-physics_archives=all"
            f"&classification-include_cross_list=include"
            f"&date-filter_by=all_dates"
            f"&date-year=&date-from_date=&date-to_date="
            f"&date-date_type=submitted_date"
            f"&abstracts=show"
            f"&size={ARXIV_PAGE_SIZE}"
            f"&order={ARXIV_SORT_ORDER}"
        )

        popup = QMessageBox(self)
        popup.setWindowTitle("OASIS - Generated Search URL")
        popup.setText("Preview of the generated ArXiv search URL:")
        popup.setDetailedText(url)
        popup.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Open)
        popup.button(QMessageBox.StandardButton.Open).setText("🔍 Open in Browser")
        result = popup.exec()
        if result == QMessageBox.StandardButton.Open:
            webbrowser.open(url)


# ----------------- Main -----------------


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = OASISScraperApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
