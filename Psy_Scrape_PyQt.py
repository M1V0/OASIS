import httpx
import pandas as pd
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox,
    QRadioButton, QButtonGroup, QProgressBar, QMessageBox, QGroupBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QFont
import sys
import urllib.parse

# ----------------- Constants -----------------
PAGE_SIZE = 100
API_BASE = "https://api.osf.io/v2/preprints/"
ELASTIC_URL = "https://share.osf.io/api/v2/search/creativeworks/_search"

# Known OSF providers
OSF_PROVIDERS = {
    "psyarxiv": "PsyArXiv",
    "socarxiv": "SocArXiv",
    "engrxiv": "engrXiv",
    "lawarxiv": "LawArXiv",
    "medrxiv": "MedArXiv",
    "ecsarxiv": "ECSarXiv",
    "thesiscommons": "Thesis Commons"
}

# ----------------- OSF API Wrapper -----------------
class OSFPreprints:
    def __init__(self, provider="psyarxiv"):
        self.provider = provider
        self.API = API_BASE
        self.client = httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=30.0)
        self.results = []
        self.abort_flag = False

    def build_params(self, query=None, page=1):
        params = {
            "filter[provider]": self.provider,
            "page[size]": PAGE_SIZE,
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

# ----------------- ElasticSearch Wrapper -----------------
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

            res = self.client.post(ELASTIC_URL, json=payload)
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

# ----------------- Worker Thread -----------------
class ScraperThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(pd.DataFrame)
    error = pyqtSignal(str)

    def __init__(self, query, provider, search_mode):
        super().__init__()
        self.query = query
        self.provider = provider
        self.search_mode = search_mode
        self.client = None

    def run(self):
        try:
            if self.search_mode == "api":
                self.client = OSFPreprints(provider=self.provider)
            else:
                self.client = ElasticPreprints(provider=self.provider)

            df = self.client.run(self.query, progress_callback=self.progress)
            self.finished.emit(df)
        except Exception as e:
            self.error.emit(str(e))

    def abort(self):
        if self.client:
            self.client.abort_flag = True

# ----------------- Info Button with Tooltip -----------------
class InfoLabel(QLabel):
    def __init__(self, text, tooltip_text):
        super().__init__(text)
        self.setToolTip(tooltip_text)
        self.setStyleSheet("""
            QLabel {
                color: #0066cc;
                font-weight: bold;
                font-size: 14px;
            }
            QLabel:hover {
                color: #0052a3;
            }
            QToolTip {
                background-color: #f9f9f9;
                color: black;
                border: 1px solid #999;
                padding: 8px;
                font-size: 12px;
                max-width: 400px;
            }
        """)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)

# ----------------- Main Window -----------------
class OSFScraperApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.scraper_thread = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("OSF Preprint R")
        self.setGeometry(100, 100, 900, 700)
        
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
                margin-top: 12px;
                padding-top: 10px;
                background-color: white;
                color: black;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLineEdit, QTextEdit, QComboBox {
                padding: 8px;
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
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton#runButton {
                background-color: #0066cc;
                color: white;
                border: none;
            }
            QPushButton#runButton:hover {
                background-color: #0052a3;
            }
            QPushButton#runButton:pressed {
                background-color: #003d7a;
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
                font-size: 13px;
                spacing: 8px;
                color: black;
                background-color: transparent;
            }
            QRadioButton::indicator {
                width: 18px;
                height: 18px;
                border-radius: 9px;
                border: 2px solid #666;
                background-color: white;
            }
            QRadioButton::indicator:checked {
                background-color: #0066cc;
                border: 2px solid #0066cc;
            }
            QRadioButton::indicator:hover {
                border: 2px solid #0066cc;
            }
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 4px;
                text-align: center;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #0066cc;
                border-radius: 3px;
            }
        """)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Query Group
        query_group = QGroupBox("Search Query")
        query_layout = QVBoxLayout()
        
        query_header = QHBoxLayout()
        query_label = QLabel("Enter your search query:")
        query_info = InfoLabel("ℹ️", 
            "OSF API Mode: Simple keyword search in titles only.\n\n"
            "Weblike Mode: Advanced search supporting:\n"
            "• Boolean operators (AND, OR, NOT)\n"
            "• Wildcards (* and ?)\n"
            "• Phrase matching with quotes\n"
            "• Field-specific searches\n"
            "• Searches both titles AND abstracts")
        query_header.addWidget(query_label)
        query_header.addWidget(query_info)
        query_header.addStretch()
        
        query_layout.addLayout(query_header)
        
        self.query_input = QTextEdit()
        self.query_input.setMaximumHeight(80)
        self.query_input.setPlaceholderText("e.g., 'cognitive therapy' or 'depression AND (anxiety OR stress)'")
        query_layout.addWidget(self.query_input)
        
        query_group.setLayout(query_layout)
        main_layout.addWidget(query_group)

        # Options Group
        options_group = QGroupBox("Scraper Options")
        options_layout = QVBoxLayout()

        # Filename row
        filename_row = QHBoxLayout()
        filename_label = QLabel("Output filename:")
        filename_info = InfoLabel("ℹ️", 
            "Base name for the output CSV file.\n"
            "Provider and search mode will be automatically appended.\n"
            "Example: 'Data_Preprints_psyarxiv_weblike.csv'")
        self.filename_input = QLineEdit("Data_Preprints")
        filename_row.addWidget(filename_label)
        filename_row.addWidget(filename_info)
        filename_row.addWidget(self.filename_input, stretch=1)
        options_layout.addLayout(filename_row)

        # Provider row
        provider_row = QHBoxLayout()
        provider_label = QLabel("Provider:")
        provider_info = InfoLabel("ℹ️", 
            "Select the preprint repository to search:\n\n"
            "• PsyArXiv: Psychology\n"
            "• SocArXiv: Social sciences\n"
            "• engrXiv: Engineering\n"
            "• LawArXiv: Legal studies\n"
            "• MedArXiv: Medicine\n"
            "• ECSarXiv: Engineering and computer science\n"
            "• Thesis Commons: Graduate theses")
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(list(OSF_PROVIDERS.keys()))
        provider_row.addWidget(provider_label)
        provider_row.addWidget(provider_info)
        provider_row.addWidget(self.provider_combo, stretch=1)
        options_layout.addLayout(provider_row)

        # Search mode row
        search_mode_row = QHBoxLayout()
        search_label = QLabel("Search Mode:")
        search_info = InfoLabel("ℹ️", 
            "OSF API: Uses official OSF setup - limited to searching titles.\n\n"
            "Weblike API: potentially unstable, searches titles AND abstracts,\n "
            "supports Boolean logic, wildcards, and advanced query syntax.")
        
        self.search_mode_group = QButtonGroup()
        self.api_radio = QRadioButton("OSF Search (Title only)")
        self.elastic_radio = QRadioButton("Weblike Search (Title + Abstract)")
        self.api_radio.setChecked(True)
        
        self.search_mode_group.addButton(self.api_radio)
        self.search_mode_group.addButton(self.elastic_radio)
        
        search_mode_row.addWidget(search_label)
        search_mode_row.addWidget(search_info)
        search_mode_row.addWidget(self.api_radio)
        search_mode_row.addWidget(self.elastic_radio)
        search_mode_row.addStretch()
        options_layout.addLayout(search_mode_row)

        options_group.setLayout(options_layout)
        main_layout.addWidget(options_group)

        # Buttons
        button_layout = QHBoxLayout()
        self.run_button = QPushButton("Run Scraper")
        self.run_button.setObjectName("runButton")
        self.run_button.clicked.connect(self.run_scraper)
        
        self.abort_button = QPushButton("Abort")
        self.abort_button.setObjectName("abortButton")
        self.abort_button.clicked.connect(self.abort_scraper)
        self.abort_button.setEnabled(False)
        
        button_layout.addStretch()
        button_layout.addWidget(self.run_button)
        button_layout.addWidget(self.abort_button)
        button_layout.addStretch()
        main_layout.addLayout(button_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.hide()
        main_layout.addWidget(self.progress_bar)

        # Feedback area
        feedback_group = QGroupBox("Results")
        feedback_layout = QVBoxLayout()
        self.feedback_text = QTextEdit()
        self.feedback_text.setReadOnly(True)
        self.feedback_text.setMaximumHeight(200)
        feedback_layout.addWidget(self.feedback_text)
        feedback_group.setLayout(feedback_layout)
        main_layout.addWidget(feedback_group)

    def run_scraper(self):
        query = self.query_input.toPlainText().strip()
        if not query:
            QMessageBox.warning(self, "Input Error", "Please enter a search query.")
            return

        provider = self.provider_combo.currentText()
        search_mode = "api" if self.api_radio.isChecked() else "weblike"

        self.feedback_text.clear()
        self.feedback_text.append(f"🔍 Starting scraper with {search_mode} mode for {provider}...\n")
        
        self.progress_bar.show()
        self.run_button.setEnabled(False)
        self.abort_button.setEnabled(True)

        self.scraper_thread = ScraperThread(query, provider, search_mode)
        self.scraper_thread.progress.connect(self.update_progress)
        self.scraper_thread.finished.connect(self.scraper_finished)
        self.scraper_thread.error.connect(self.scraper_error)
        self.scraper_thread.start()

    def abort_scraper(self):
        if self.scraper_thread:
            self.feedback_text.append("\n⚠️ Aborting scraper...\n")
            self.scraper_thread.abort()
            self.abort_button.setEnabled(False)

    def update_progress(self, message):
        self.feedback_text.append(message)
        self.feedback_text.ensureCursorVisible()

    def scraper_finished(self, df):
        self.progress_bar.hide()
        self.run_button.setEnabled(True)
        self.abort_button.setEnabled(False)

        # Check if scraper was aborted
        if self.scraper_thread and self.scraper_thread.client and self.scraper_thread.client.abort_flag:
            self.feedback_text.append("\n⛔ Retrieval aborted by user.\n")
            QMessageBox.information(self, "Aborted", "Retrieval aborted by user.")
            return

        if df.empty:
            self.feedback_text.append("\n❌ No preprints found.\n")
            QMessageBox.warning(self, "No Results", "No preprints were found for your query.")
            return

        base_filename = self.filename_input.text().strip() or "Data_Preprints"
        provider = self.provider_combo.currentText()
        search_mode = "api" if self.api_radio.isChecked() else "weblike"
        filename = f"{base_filename}_{provider}_{search_mode}.csv"
        
        df.to_csv(filename, index=False)
        
        msg = f"\n✅ Scraping complete! {len(df)} unique preprints saved to '{filename}'\n"
        self.feedback_text.append(msg)
        QMessageBox.information(self, "Success", msg)

    def scraper_error(self, error_msg):
        self.progress_bar.hide()
        self.run_button.setEnabled(True)
        self.abort_button.setEnabled(False)
        
        self.feedback_text.append(f"\n❌ Error: {error_msg}\n")
        QMessageBox.critical(self, "Error", f"An error occurred:\n{error_msg}")

# ----------------- Main -----------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Modern look
    window = OSFScraperApp()
    window.show()
    sys.exit(app.exec())
