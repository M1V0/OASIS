import httpx
import pandas as pd
import re
import webbrowser
import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox,
    QRadioButton, QButtonGroup, QProgressBar, QMessageBox, QGroupBox,
    QTabWidget, QFrame, QGridLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QPixmap, QIcon, QMovie
from bs4 import BeautifulSoup

# ==================== CONSTANTS AND CONFIGURATION ====================

# ArXiv constants
ARXIV_PAGE_SIZE = 200
ARXIV_SORT_ORDER = "-announced_date_first"

ARXIV_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/106.0.0.0 Safari/537.36"
}

# OSF constants
OSF_PAGE_SIZE = 100
OSF_API_BASE = "https://api.osf.io/v2/preprints/"
OSF_ELASTIC_URL = "https://share.osf.io/api/v2/search/creativeworks/_search"

# Server configurations
SERVERS = {
    "ArXiv": {
        "type": "arxiv",
        "display_name": "ArXiv",
        "fields": ["all", "title", "abstract", "author"],
        "operators": ["AND", "OR"]
    },
    "PsyArXiv": {
        "type": "osf",
        "display_name": "PsyArXiv",
        "provider": "psyarxiv"
    },
    "SocArXiv": {
        "type": "osf", 
        "display_name": "SocArXiv",
        "provider": "socarxiv"
    },
    "engrXiv": {
        "type": "osf",
        "display_name": "engrXiv",
        "provider": "engrxiv"
    },
    "LawArXiv": {
        "type": "osf",
        "display_name": "LawArXiv",
        "provider": "lawarxiv"
    },
    "MedArXiv": {
        "type": "osf",
        "display_name": "MedArXiv",
        "provider": "medrxiv"
    },
    "ECSarXiv": {
        "type": "osf",
        "display_name": "ECSarXiv", 
        "provider": "ecsarxiv"
    },
    "Thesis Commons": {
        "type": "osf",
        "display_name": "Thesis Commons",
        "provider": "thesiscommons"
    }
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

# ==================== ARXIV SCRAPER FUNCTIONS ====================

def extract_text(soup, selector):
    try:
        return soup.select_one(selector).get_text(strip=True)
    except AttributeError:
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
            if a_tag and 'href' in a_tag.attrs:
                arxiv_id = a_tag['href'].split("/")[-1]

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

def scrape_arxiv(url, feedback_callback=None, progress_callback=None):
    client = httpx.Client(headers=ARXIV_HEADERS)
    all_results = {}
    page = 0

    while True:
        page_url = f"{url}&start={page*ARXIV_PAGE_SIZE}"
        msg = f"Fetching ArXiv page {page+1}..."
        print(msg)
        if feedback_callback:
            feedback_callback.emit(msg)

        res = client.get(page_url, timeout=15)
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

def build_arxiv_url_from_conditions(conditions):
    if not conditions:
        return ""
    first_operator = conditions[0]['operator']
    field = conditions[0]['field']
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
        f"&terms-0-field={field}"
        f"&classification-physics_archives=all"
        f"&classification-include_cross_list=include"
        f"&date-filter_by=all_dates"
        f"&date-year=&date-from_date=&date-to_date="
        f"&date-date_type=submitted_date"
        f"&abstracts=show"
        f"&size={ARXIV_PAGE_SIZE}"
        f"&order={ARXIV_SORT_ORDER}"
    )
    return url

# ==================== OSF SCRAPER FUNCTIONS ====================

class OSFPreprints:
    def __init__(self, provider="psyarxiv"):
        self.provider = provider
        self.API = OSF_API_BASE
        self.client = httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=30.0)
        self.results = []
        self.abort_flag = False

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
        res = self.client.get(self.API, params=params)
        res.raise_for_status()
        return res.json()

    def parse_response(self, data):
        rows = []
        for item in data.get("data", []):
            if self.abort_flag:
                break
            attrs = item.get("attributes", {}) or {}
            title = attrs.get("title", "") or ""
            desc = attrs.get("description", "") or ""
            date = attrs.get("date_published", "") or ""
            tags = attrs.get("tags", []) or []
            doi = attrs.get("doi", "") or ""
            url = item.get("links", {}).get("html", "") or ""
            _id = item.get("id", "") or ""

            rows.append({
                "ID": _id,
                "Title": title,
                "Abstract": desc,
                "Date Published": date,
                "Tags": ",".join([t if isinstance(t, str) else str(t) for t in tags]),
                "DOI": doi,
                "URL": url,
                "Contributors": "",
                "Provider": self.provider,
            })
        return rows

    def run(self, query, progress_callback=None):
        self.results = []
        page = 1
        while True:
            if self.abort_flag:
                break
            data = self.fetch_page(query, page)
            if data is None:
                break
            for row in self.parse_response(data):
                if self.abort_flag:
                    break
                self.results.append(row)
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
    def __init__(self, provider="psyarxiv"):
        self.provider = provider
        self.client = httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=30.0)
        self.abort_flag = False

    def run(self, query, progress_callback=None):
        rows = []
        size = 200
        start = 0

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

            res = self.client.post(OSF_ELASTIC_URL, json=payload)
            res.raise_for_status()
            data = res.json()
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break

            for h in hits:
                if self.abort_flag:
                    break
                s = h.get("_source", {})

                url = ""
                links = s.get("links", {})
                if isinstance(links, dict):
                    url = links.get("html", "")

                contributors = []
                lists_contribs = s.get("lists", {}).get("contributors", [])
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
                    "URL": url,
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

# ==================== WORKER THREAD ====================

class ScraperThread(QThread):
    progress = pyqtSignal(str)
    progress_value = pyqtSignal(int)
    finished = pyqtSignal(pd.DataFrame)
    error = pyqtSignal(str)

    def __init__(self, server_config, query, search_mode, conditions=None, url=None):
        super().__init__()
        self.server_config = server_config
        self.query = query
        self.search_mode = search_mode
        self.conditions = conditions
        self.url = url
        self.client = None
        self.abort_flag = False

    def run(self):
        try:
            if self.server_config["type"] == "arxiv":
                # ArXiv scraping
                if self.url:
                    final_url = self.url
                else:
                    final_url = build_arxiv_url_from_conditions(self.conditions)
                
                self.progress.emit(f"Starting ArXiv scrape with URL: {final_url}")
                results = scrape_arxiv(
                    final_url, 
                    feedback_callback=self.progress,
                    progress_callback=self.progress_value
                )
                df = pd.DataFrame(results)
            else:
                # OSF scraping
                provider = self.server_config["provider"]
                if self.search_mode == "api":
                    self.client = OSFPreprints(provider=provider)
                else:
                    self.client = ElasticPreprints(provider=provider)
                
                df = self.client.run(self.query, progress_callback=self.progress)
            
            self.finished.emit(df)
            
        except Exception as e:
            self.error.emit(str(e))

    def abort(self):
        self.abort_flag = True
        if self.client:
            self.client.abort_flag = True

# ==================== INFO LABEL WITH QUESTION MARK ====================

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
                border-radius: 8px;  /* half of width/height to make circle */
                min-width: 16px;
                min-height: 16px;
                max-width: 16px;
                max-height: 16px;
                margin: 2px;
            }
            QLabel:hover {
                background-color: #cce7ff;
                color: #004499;
            }
            QToolTip {
                background-color: #ffffe0;
                color: black;
                border: 2px solid #ffd700;
                padding: 8px;
                font-size: 12px;
                max-width: 400px;
                border-radius: 4px;
            }
        """)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


# ==================== MAIN WINDOW ====================

class OASISScraperApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.scraper_thread = None
        self.current_server = "ArXiv"
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("OASIS - Open ArXiv Scraper for Implementing Systematic Reviews")
        self.setGeometry(100, 100, 900, 650)  # More compact window size
        
        # Apply modern stylesheet
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QLabel {
                color: black;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
                background-color: white;
                color: black;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLineEdit, QTextEdit, QComboBox {
                padding: 6px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: white;
                color: black;
                font-size: 13px;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
                border: 2px solid #0066cc;
            }
            QPushButton {
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton#runButton {
                background-color: #28a745;
                color: white;
                border: none;
            }
            QPushButton#runButton:hover {
                background-color: #218838;
            }
            QPushButton#runButton:pressed {
                background-color: #1e7e34;
            }
            QPushButton#abortButton {
                background-color: #dc3545;
                color: white;
                border: none;
            }
            QPushButton#abortButton:hover {
                background-color: #c82333;
            }
            QRadioButton {
                font-size: 12px;
                spacing: 6px;
                color: black;
                background-color: transparent;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 2px solid #666;
                background-color: white;
            }
            QRadioButton::indicator:checked {
                background-color: #28a745;
                border: 2px solid #28a745;
            }
            QRadioButton::indicator:hover {
                border: 2px solid #28a745;
            }
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 4px;
                text-align: center;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #28a745;
                border-radius: 3px;
            }
            QTabWidget::pane {
                border: 1px solid #ccc;
                background-color: white;
            }
            QTabBar::tab {
                background-color: #e0e0e0;
                padding: 6px 12px;
                margin-right: 2px;
                border-radius: 4px;
                font-size: 12px;
            }
            QTabBar::tab:selected {
                background-color: #28a745;
                color: white;
            }
        """)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)  # Reduced spacing
        main_layout.setContentsMargins(15, 15, 15, 15)  # Reduced margins

        # Header with OASIS branding and graphic
        header_frame = QFrame()
        header_frame.setStyleSheet("QFrame { background-color: #2c5aa0; border-radius: 6px; padding: 8px; }")
        header_layout = QHBoxLayout(header_frame)
        
        # Graphic placeholder
        try:
            graphic_pixmap = QPixmap("OASIS.png")
            if not graphic_pixmap.isNull():
                graphic_label = QLabel()
                graphic_label.setPixmap(graphic_pixmap.scaled(75, 75, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            else:
                graphic_label = QLabel("🌐")
                graphic_label.setStyleSheet("font-size: 40px; color: white;")
                graphic_label.setFixedSize(60, 60)
        except:
            graphic_label = QLabel("🌐")
            graphic_label.setStyleSheet("font-size: 40px; color: white;")
            graphic_label.setFixedSize(60, 60)
        
        # Title section
        title_layout = QVBoxLayout()
        title_label = QLabel("OASIS")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: white;
                padding: 2px;
            }
        """)
        subtitle_label = QLabel("Open ArXiv Scraper for Implementing Systematic Reviews")
        subtitle_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #e6e6e6;
                font-style: italic;
                padding: 1px;
            }
        """)
        title_layout.addWidget(title_label)
        title_layout.addWidget(subtitle_label)
        
        header_layout.addWidget(graphic_label)
        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        
        main_layout.addWidget(header_frame)

        # Combined Server and Strategy Selection
        config_group = QGroupBox("Search Configuration")
        config_layout = QHBoxLayout()
        
        # Server selection
        server_label = QLabel("Server:")
        server_info = InfoLabel("Choose which preprint server to search. \nArXiv covers physics, math, CS, etc.\nOSF servers are discipline-specific.")
        
        self.server_combo = QComboBox()
        self.server_combo.addItems(list(SERVERS.keys()))
        self.server_combo.currentTextChanged.connect(self.server_changed)
        
        # Strategy selection
        self.strategy_label = QLabel("Strategy:")
        self.strategy_info = InfoLabel("OSF API: Official. Faster, title-only search\nWeblike Search: Unofficial OSF search, mimics the web search.\n Slower, searches titles AND abstracts")
        
        self.strategy_group = QButtonGroup()
        self.standard_radio = QRadioButton("OSF API")
        self.comprehensive_radio = QRadioButton("Weblike API")
        self.standard_radio.setChecked(True)
        
        self.strategy_group.addButton(self.standard_radio)
        self.strategy_group.addButton(self.comprehensive_radio)
        
        # Add widgets to layout
        config_layout.addWidget(server_label)
        config_layout.addWidget(server_info)
        config_layout.addWidget(self.server_combo)
        config_layout.addStretch()
        config_layout.addWidget(self.strategy_label)
        config_layout.addWidget(self.strategy_info)
        config_layout.addWidget(self.standard_radio)
        config_layout.addWidget(self.comprehensive_radio)

        
        config_group.setLayout(config_layout)
        main_layout.addWidget(config_group)

        # Create tab widget for different search modes
        self.tabs = QTabWidget()
        
        # ArXiv tab (Build Query)
        self.arxiv_build_tab = QWidget()
        self.setup_arxiv_build_tab()
        self.tabs.addTab(self.arxiv_build_tab, "Build Query")
        
        # ArXiv tab (Paste URL)
        self.arxiv_paste_tab = QWidget()
        self.setup_arxiv_paste_tab()
        self.tabs.addTab(self.arxiv_paste_tab, "Paste URL")
        
        # OSF tab
        self.osf_tab = QWidget()
        self.setup_osf_tab()
        self.tabs.addTab(self.osf_tab, "OSF Query")
        
        main_layout.addWidget(self.tabs)

        # Combined Options and Buttons
        action_group = QGroupBox("Output & Actions")
        action_layout = QHBoxLayout()
        
        # Filename
        filename_label = QLabel("Filename:")
        filename_info = InfoLabel("Base filename for CSV output. \nServer and mode will be appended automatically.")
        
        self.filename_input = QLineEdit("SystematicReview_Data")
        self.filename_input.setToolTip("Base filename for systematic review screening data")
        
        # Buttons
        self.preview_button = QPushButton("Preview URL")
        self.preview_button.clicked.connect(self.preview_url)
        
        self.run_button = QPushButton("Start Search")
        self.run_button.setObjectName("runButton")
        self.run_button.clicked.connect(self.run_scraper)
        
        # Prepare spinner but don’t show yet
        self.spinner_movie = QMovie("spinner.gif")
        self.spinner_movie.setScaledSize(QSize(16, 16))  # make spinner small enough
        
        self.abort_button = QPushButton("Abort")
        self.abort_button.setObjectName("abortButton")
        self.abort_button.clicked.connect(self.abort_scraper)
        self.abort_button.setEnabled(False)
        
        # Add to layout
        action_layout.addWidget(filename_label)
        action_layout.addWidget(filename_info)
        action_layout.addWidget(self.filename_input)
        action_layout.addStretch()
        action_layout.addWidget(self.preview_button)
        action_layout.addWidget(self.run_button)
        action_layout.addWidget(self.abort_button)
        
        action_group.setLayout(action_layout)
        main_layout.addWidget(action_group)

        # Feedback area
        feedback_group = QGroupBox("Results")
        feedback_layout = QVBoxLayout()
        
        self.feedback_text = QTextEdit()
        self.feedback_text.setReadOnly(True)
        self.feedback_text.setMaximumHeight(120)  # Reduced height
        self.feedback_text.setPlaceholderText("Search progress and results will appear here...")
        
        feedback_layout.addWidget(self.feedback_text)
        feedback_group.setLayout(feedback_layout)
        main_layout.addWidget(feedback_group)
        
        # Footer section
        footer_frame = QFrame()
        footer_layout = QHBoxLayout(footer_frame)
        footer_layout.setContentsMargins(0, 5, 0, 0)
        
        license_link = QLabel('<a href="https://creativecommons.org/licenses/by/4.0/">CC-BY License</a>')
        license_link.setOpenExternalLinks(True)
        license_link.setStyleSheet("color: #0066cc;")
        
        github_link = QLabel('<a href="https://github.com/M1V0/OASIS">GitHub</a>')
        github_link.setOpenExternalLinks(True)
        github_link.setStyleSheet("color: #0066cc;")
        
        creator_label = QLabel("Created by Matthew Ivory")
        creator_label.setStyleSheet("color: gray; font-size: 11px;")
        
        footer_layout.addWidget(license_link)
        footer_layout.addSpacing(15)
        footer_layout.addWidget(github_link)
        footer_layout.addStretch()
        footer_layout.addWidget(creator_label)
        
        main_layout.addWidget(footer_frame)

        # Initialize UI state
        self.server_changed("ArXiv")

    def setup_arxiv_build_tab(self):
        layout = QVBoxLayout(self.arxiv_build_tab)
        layout.setSpacing(8)
        
        # Condition builder
        condition_group = QGroupBox("Search Conditions")
        condition_layout = QVBoxLayout()
        
        # Condition rows container
        self.condition_rows_widget = QWidget()
        self.condition_rows_layout = QGridLayout(self.condition_rows_widget)
        self.condition_rows_layout.setColumnStretch(3, 1)
        self.condition_rows_layout.setVerticalSpacing(5)
        
        # Headers
        self.condition_rows_layout.addWidget(QLabel("#"), 0, 0)
        self.condition_rows_layout.addWidget(QLabel("Operator"), 0, 1)
        self.condition_rows_layout.addWidget(QLabel("Field"), 0, 2)
        self.condition_rows_layout.addWidget(QLabel("Search Term"), 0, 3)
        
        condition_layout.addWidget(self.condition_rows_widget)
        
        # Add/Remove buttons
        button_layout = QHBoxLayout()
        self.add_condition_button = QPushButton("➕ Add Term")
        self.add_condition_button.clicked.connect(self.add_condition_row)
        self.remove_condition_button = QPushButton("➖ Remove Term")
        self.remove_condition_button.clicked.connect(self.remove_condition_row)
        
        button_layout.addWidget(self.add_condition_button)
        button_layout.addWidget(self.remove_condition_button)
        button_layout.addStretch()
        
        condition_layout.addLayout(button_layout)
        condition_group.setLayout(condition_layout)
        layout.addWidget(condition_group)
        
        # Add initial condition row
        self.condition_rows = []
        self.add_condition_row()

    def setup_arxiv_paste_tab(self):
        layout = QVBoxLayout(self.arxiv_paste_tab)
        
        paste_group = QGroupBox("Paste ArXiv URL")
        paste_layout = QVBoxLayout()
        
        url_info = InfoLabel("Paste a complete ArXiv advanced search URL. \nThe tool will optimise it for systematic review data extraction.")
        
        self.paste_url_text = QTextEdit()
        self.paste_url_text.setMaximumHeight(80)
        self.paste_url_text.setPlaceholderText("Paste your ArXiv search URL here...\nExample: https://arxiv.org/search/advanced?advanced=...")
        
        paste_layout.addWidget(url_info)
        paste_layout.addWidget(self.paste_url_text)
        paste_group.setLayout(paste_layout)
        
        layout.addWidget(paste_group)

    def setup_osf_tab(self):
        layout = QVBoxLayout(self.osf_tab)
        
        # Query input
        query_group = QGroupBox("Search Query")
        query_layout = QVBoxLayout()
        
        query_info = InfoLabel("Enter search terms. \nOSF API mode searches titles only. \nWeblike Search mode supports Boolean operators \nand searches titles + abstracts.")
        
        self.osf_query_input = QTextEdit()
        self.osf_query_input.setMaximumHeight(60)
        self.osf_query_input.setPlaceholderText("Enter search terms...\n e.g. 'cognitive therapy AND depression'")
        
        query_layout.addWidget(query_info)
        query_layout.addWidget(self.osf_query_input)
        query_group.setLayout(query_layout)
        layout.addWidget(query_group)

    def add_condition_row(self):
        row_index = len(self.condition_rows) + 1  # +1 because of header row
        
        row = {}
        
        # Operator
        op_var = QComboBox()
        op_var.addItems(["AND", "OR"])
        if len(self.condition_rows) == 0:
            op_var.setEnabled(False)  # First row doesn't need operator
        row['operator'] = op_var
        
        # Field
        field_var = QComboBox()
        field_var.addItems(SERVERS["ArXiv"]["fields"])
        row['field'] = field_var
        
        # Value
        value_var = QLineEdit()
        value_var.setPlaceholderText("Enter search term...")
        row['value'] = value_var
        
        # Add to layout
        self.condition_rows_layout.addWidget(QLabel(f"{len(self.condition_rows) + 1}."), row_index, 0)
        self.condition_rows_layout.addWidget(op_var, row_index, 1)
        self.condition_rows_layout.addWidget(field_var, row_index, 2)
        self.condition_rows_layout.addWidget(value_var, row_index, 3)
        
        self.condition_rows.append(row)

    def remove_condition_row(self):
        if len(self.condition_rows) > 0:
            last_row = self.condition_rows.pop()
            # Remove widgets from layout
            row_index = len(self.condition_rows) + 1  # +1 because of header row
            for i in reversed(range(self.condition_rows_layout.count())):
                widget = self.condition_rows_layout.itemAt(i).widget()
                if widget in [last_row['operator'], last_row['field'], last_row['value']]:
                    widget.deleteLater()
            
            # Remove the number label
            for i in reversed(range(self.condition_rows_layout.count())):
                widget = self.condition_rows_layout.itemAt(i).widget()
                if isinstance(widget, QLabel) and widget.text() == f"{len(self.condition_rows) + 1}.":
                    widget.deleteLater()
                    break

    def server_changed(self, server_name):
        self.current_server = server_name
        server_config = SERVERS[server_name]
        
        if server_config["type"] == "arxiv":
            # Hide strategy widgets
            self.strategy_label.setVisible(False)
            self.strategy_info.setVisible(False)
            self.standard_radio.setVisible(False)
            self.comprehensive_radio.setVisible(False)
    
            # Show ArXiv tabs, hide OSF tab
            self.tabs.setTabVisible(0, True)   # Build Query
            self.tabs.setTabVisible(1, True)   # Paste URL
            self.tabs.setTabVisible(2, False)  # OSF Query
            self.tabs.setCurrentIndex(0)
            self.preview_button.setVisible(True)
    
        else:
            # Show strategy widgets
            self.strategy_label.setVisible(True)
            self.strategy_info.setVisible(True)
            self.standard_radio.setVisible(True)
            self.comprehensive_radio.setVisible(True)
    
            # Show OSF tab, hide ArXiv tabs
            self.tabs.setTabVisible(0, False)
            self.tabs.setTabVisible(1, False)
            self.tabs.setTabVisible(2, True)
            self.tabs.setCurrentIndex(2)
            self.preview_button.setVisible(False)

    def run_scraper(self):
        server_config = SERVERS[self.current_server]
        base_filename = self.filename_input.text().strip() or "SystematicReview_Data"
        
        self.feedback_text.clear()
        self.spinner_movie.start()
        self.run_button.setEnabled(False)
        self.run_button.setText(" Searching...")  # Add space for spinner
        self.run_button.setIcon(QIcon(self.spinner_movie.currentPixmap()))
        self.spinner_movie.frameChanged.connect(
            lambda: self.run_button.setIcon(QIcon(self.spinner_movie.currentPixmap()))
        )
        self.spinner_movie.start()
        self.abort_button.setEnabled(True)


        try:
            if server_config["type"] == "arxiv":
                # ArXiv scraping
                if self.tabs.currentIndex() == 0:  # Build Query tab
                    conditions = []
                    for row in self.condition_rows:
                        field = row['field'].currentText()
                        operator = row['operator'].currentText() if row['operator'].isEnabled() else "AND"
                        value = row['value'].text().strip()
                        if value:
                            conditions.append({'field': field, 'operator': operator, 'value': value})
                    
                    if not conditions:
                        QMessageBox.warning(self, "Input Error", "Add at least one search term.")
                        return
                    
                    self.scraper_thread = ScraperThread(
                        server_config=server_config,
                        query="",
                        search_mode="",
                        conditions=conditions
                    )
                    
                else:  # Paste URL tab
                    url = self.paste_url_text.toPlainText().strip()
                    if not url:
                        QMessageBox.warning(self, "Input Error", "Please paste a valid ArXiv search URL.")
                        return
                    
                    # Force page size and order
                    url = re.sub(r'size=\d+', f"size={ARXIV_PAGE_SIZE}", url)
                    if "order=" in url:
                        url = re.sub(r'order=[^&]+', f"order={ARXIV_SORT_ORDER}", url)
                    else:
                        url += f"&order={ARXIV_SORT_ORDER}"
                    
                    self.scraper_thread = ScraperThread(
                        server_config=server_config,
                        query="", 
                        search_mode="",
                        url=url
                    )
                    
            else:
                # OSF scraping
                query = self.osf_query_input.toPlainText().strip()
                if not query:
                    QMessageBox.warning(self, "Input Error", "Please enter search terms.")
                    return
                
                search_mode = "api" if self.standard_radio.isChecked() else "weblike"
                
                self.scraper_thread = ScraperThread(
                    server_config=server_config,
                    query=query,
                    search_mode=search_mode
                )
            
            # Connect thread signals
            self.scraper_thread.progress.connect(self.update_progress)
            self.scraper_thread.finished.connect(self.scraper_finished)
            self.scraper_thread.error.connect(self.scraper_error)
            self.scraper_thread.start()
            
        except Exception as e:
            self.scraper_error(str(e))

    def abort_scraper(self):
        if self.scraper_thread:
            self.feedback_text.append("\n⚠️ Aborting search...\n")
            self.scraper_thread.abort()
            self.abort_button.setEnabled(False)

    def update_progress(self, message):
        self.feedback_text.append(message)
        self.feedback_text.ensureCursorVisible()

    def scraper_finished(self, df):
        self.spinner_movie.stop()
        self.run_button.setEnabled(True)
        self.run_button.setText("Start Search")
        self.run_button.setIcon(QIcon())  # remove spinner
        self.run_button.setEnabled(True)
        self.abort_button.setEnabled(False)

        if df.empty:
            self.feedback_text.append("\n❌ No preprints found.\n")
            QMessageBox.warning(self, "No Results", "No preprints were found matching your criteria.")
            return

        base_filename = self.filename_input.text().strip() or "SystematicReview_Data"
        server_name = self.current_server
        
        if SERVERS[server_name]["type"] == "arxiv":
            filename = f"{base_filename}_{server_name}.csv"
        else:
            search_mode = "OSF_API" if self.standard_radio.isChecked() else "weblike"
            filename = f"{base_filename}_{server_name}_{search_mode}.csv"
        
        df.to_csv(filename, index=False)
        
        msg = f"\n✅ Search complete! {len(df)} preprints saved to '{filename}'"
        self.feedback_text.append(msg)
        QMessageBox.information(self, "Search Complete", 
                               f"Successfully collected {len(df)} preprints.\n\nFile saved as: {filename}")

    def scraper_error(self, error_msg):
        self.spinner_movie.stop()
        self.run_button.setEnabled(True)
        self.run_button.setText("Start Search")
        self.run_button.setIcon(QIcon())  # remove spinner
        self.run_button.setEnabled(True)
        self.abort_button.setEnabled(False)
        
        self.feedback_text.append(f"\n❌ Error: {error_msg}\n")
        QMessageBox.critical(self, "Search Error", f"An error occurred:\n{error_msg}")

    def preview_url(self):
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

        url = build_arxiv_url_from_conditions(conditions)

        popup = QMessageBox(self)
        popup.setWindowTitle("OASIS - Generated Search URL")
        popup.setText("Preview of the generated ArXiv search URL:")
        popup.setDetailedText(url)
        popup.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Open)
        popup.button(QMessageBox.StandardButton.Open).setText("🔍 Open in Browser")
        
        result = popup.exec()
        if result == QMessageBox.StandardButton.Open:
            webbrowser.open(url)

# ==================== MAIN ====================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName("OASIS")
    app.setApplicationVersion("1.0")
    
    window = OASISScraperApp()
    window.show()
    sys.exit(app.exec())
