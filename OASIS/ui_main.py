# GUI code extracted from monolithic OASIS.py - builds the GUI and wires signals.
import os
import re
import logging
import webbrowser
from datetime import datetime

import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QComboBox, QRadioButton, QButtonGroup, QMessageBox,
    QGroupBox, QTabWidget, QFrame, QGridLayout, QCheckBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QIcon, QMovie

from .config import SERVERS, POLITENESS_CONFIG
from .utils import unique_filename
from .scrapers.threads import ScraperThread

class OASISWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.info_style = """
        QLabel {
            border: 1px solid #888;
            border-radius: 8px;
            color: #555;
            font-weight: bold;
            font-family: Arial;
            font-size: 11px;
            min-width: 16px;
            min-height: 16px;
            max-width: 16px;
            max-height: 16px;
            text-align: center;
            qproperty-alignment: 'AlignCenter';
        }
        QLabel:hover {
            background-color: #e0e0e0;
        }
        """
        # logging per-session file
        os.makedirs("logs", exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_filename = os.path.join("logs", f"OASIS_Log_{timestamp}.txt")
        logging.basicConfig(filename=self.log_filename, level=logging.INFO,
                            format="%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
        logging.info("=== New OASIS session started ===")

        self.scraper_thread = None
        self.current_server = "ArXiv"
        self.spinner_movie = None

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Header area
        header_layout = QHBoxLayout()
        self.logo_label = QLabel()
        pixmap = QPixmap("var/OASIS.png")
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaledToHeight(60, Qt.TransformationMode.SmoothTransformation)
            self.logo_label.setPixmap(scaled_pixmap)
        header = QLabel("OASIS — Open ArXiv Scraper for Implementing Systematic Reviews")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        header_layout.addWidget(self.logo_label)
        header_layout.addSpacing(10)
        header_layout.addWidget(header)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Config group
        config_group = QGroupBox("Search Configuration")
        config_layout = QHBoxLayout()

        server_label = QLabel("Server:")
        server_info = QLabel("?")
        server_info.setStyleSheet(self.info_style)
        server_info.setToolTip("Choose which preprint server to search.")
        # Replace dropdown with radio buttons
        self.server_button_group = QButtonGroup(self)
        self.arxiv_radio = QRadioButton("ArXiv")
        self.osf_radio = QRadioButton("OSF")
        self.arxiv_radio.setChecked(True)
        self.server_button_group.addButton(self.arxiv_radio)
        self.server_button_group.addButton(self.osf_radio)
        # connect radios
        self.arxiv_radio.toggled.connect(lambda checked: self.server_changed("ArXiv") if checked else None)
        self.osf_radio.toggled.connect(lambda checked: self.server_changed("OSF") if checked else None)

        # OSF repositories presented horizontally as checkboxes (hidden for ArXiv)
        self.osf_repo_widget = QWidget()
        osf_repo_layout = QHBoxLayout(self.osf_repo_widget)
        osf_repo_layout.setContentsMargins(0, 0, 0, 0)
        self.osf_server_checks = []
        # default list kept as before
        osf_providers = ["PsyArXiv", "SocArXiv", "LawArXiv"]
        for name in osf_providers:
            cb = QCheckBox(name)
            cb.setChecked(False)
            self.osf_server_checks.append(cb)
            osf_repo_layout.addWidget(cb)
        osf_repo_layout.addStretch()

        # Strategy (for OSF only)
        self.strategy_label = QLabel("Strategy:")
        self.strategy_info = QLabel("?")
        self.strategy_info.setStyleSheet(self.info_style)
        self.strategy_info.setToolTip("Choose whether to use the OSF API (title search only) or the Weblike search (title, abstract, and keywords).")
        self.standard_radio = QRadioButton("OSF API")
        self.comprehensive_radio = QRadioButton("Weblike API")
        self.standard_radio.setChecked(True)

        politeness_label = QLabel("Politeness:")
        politeness_info = QLabel("?")
        politeness_info.setStyleSheet(self.info_style)
        politeness_info.setToolTip("Choose the frequency of requests, faster requests may result in rate limiting.")
        self.politeness_combo = QComboBox()
        self.politeness_combo.addItems(list(POLITENESS_CONFIG.keys()))
        self.politeness_combo.setCurrentText("Normal")

        # Put server selection and radios in a vertical widget so OSF repos can sit on a new line below
        server_widget = QWidget()
        server_vlayout = QVBoxLayout(server_widget)
        server_vlayout.setContentsMargins(0, 0, 0, 0)
        top_row = QHBoxLayout()
        top_row.addWidget(server_label)
        top_row.addWidget(server_info)
        top_row.addWidget(self.arxiv_radio)
        top_row.addWidget(self.osf_radio)
        top_row.addStretch()
        server_vlayout.addLayout(top_row)
        server_vlayout.addWidget(self.osf_repo_widget)

        config_layout.addWidget(server_widget)
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

        # Tabs (arxiv build/paste_query/paste_url + OSF)
        self.tabs = QTabWidget()
        self.arxiv_build_tab = QWidget()
        self.arxiv_paste_query_tab = QWidget()
        self.arxiv_paste_tab = QWidget()
        self.osf_tab = QWidget()
        self.tabs.addTab(self.arxiv_build_tab, "Build Query")
        self.tabs.addTab(self.arxiv_paste_query_tab, "Write/Paste Query")
        self.tabs.addTab(self.arxiv_paste_tab, "Paste URL")
        self.tabs.addTab(self.osf_tab, "OSF Query")
        layout.addWidget(self.tabs)

        # Setup each tab content (mirrors original UI)
        self.setup_arxiv_build_tab()
        self.setup_arxiv_paste_query_tab()
        self.setup_arxiv_paste_tab()
        self.setup_osf_tab()

        # Actions
        action_group = QGroupBox("Output & Actions")
        action_layout = QHBoxLayout()

        filename_label = QLabel("Filename base:")
        filename_info = QLabel("?")
        filename_info.setStyleSheet(self.info_style)
        filename_info.setToolTip("Output file name")
        self.filename_input = QLineEdit("OASIS_search")

        self.preview_button = QPushButton("Preview URL")
        self.preview_button.clicked.connect(self.preview_url)

        self.run_button = QPushButton("Start Search")
        self.run_button.setObjectName("runButton")

        self.abort_button = QPushButton("Abort")
        self.abort_button.setObjectName("abortButton")
        self.abort_button.setEnabled(False)

        self.run_button.clicked.connect(self.run_scraper)
        self.abort_button.clicked.connect(self.abort_scraper)

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

        # Footer
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

        # initial state
        self.server_changed("ArXiv")

    def setup_arxiv_build_tab(self):
        layout = QVBoxLayout(self.arxiv_build_tab)
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
        self.remove_condition_button = QPushButton("➖ Remove Term")
        self.add_condition_button.clicked.connect(self.add_condition_row)
        self.remove_condition_button.clicked.connect(self.remove_condition_row)
        btn_layout.addWidget(self.add_condition_button)
        btn_layout.addWidget(self.remove_condition_button)
        btn_layout.addStretch()
        cond_layout.addLayout(btn_layout)
        cond_group.setLayout(cond_layout)
        layout.addWidget(cond_group)

        self.condition_rows = []
        self.add_condition_row()

    def setup_arxiv_paste_query_tab(self):
        layout = QVBoxLayout(self.arxiv_paste_query_tab)
        group = QGroupBox("Paste ArXiv Query")
        g_l = QVBoxLayout()
        info = QLabel("?")
        info.setStyleSheet(self.info_style)
        info.setToolTip("Paste an ArXiv query string (e.g., advanced query parts) to be used directly for searching.")
        self.paste_query_text = QTextEdit()
        self.paste_query_text.setMaximumHeight(80)
        self.paste_query_text.setPlaceholderText("e.g. all:machine learning AND ti:\"deep learning\"")
        g_l.addWidget(info)
        g_l.addWidget(self.paste_query_text)
        group.setLayout(g_l)
        layout.addWidget(group)

    def setup_arxiv_paste_tab(self):
        layout = QVBoxLayout(self.arxiv_paste_tab)
        group = QGroupBox("Paste ArXiv Advanced Search URL")
        g_l = QVBoxLayout()
        info = QLabel("?")
        info.setStyleSheet(self.info_style)
        info.setToolTip("Paste a complete ArXiv advanced search URL. The tool will optimise it for systematic extraction.")
        self.paste_url_text = QTextEdit()
        self.paste_url_text.setMaximumHeight(80)
        g_l.addWidget(info)
        g_l.addWidget(self.paste_url_text)
        group.setLayout(g_l)
        layout.addWidget(group)

    def setup_osf_tab(self):
        layout = QVBoxLayout(self.osf_tab)
        # inner tabs for OSF: Build Query (like ArXiv) or Free Text / Paste Query
        self.osf_inner_tabs = QTabWidget()
        self.osf_build_tab = QWidget()
        self.osf_free_tab = QWidget()
        self.osf_inner_tabs.addTab(self.osf_build_tab, "Build Query")
        self.osf_inner_tabs.addTab(self.osf_free_tab, "Write/paste query")
        layout.addWidget(self.osf_inner_tabs)

        # Build Query similar to ArXiv
        build_layout = QVBoxLayout(self.osf_build_tab)
        cond_group = QGroupBox("OSF Search Conditions")
        cond_layout = QVBoxLayout()

        self.osf_condition_rows_widget = QWidget()
        self.osf_condition_rows_layout = QGridLayout(self.osf_condition_rows_widget)
        self.osf_condition_rows_layout.addWidget(QLabel("#"), 0, 0)
        self.osf_condition_rows_layout.addWidget(QLabel("Operator"), 0, 1)
        self.osf_condition_rows_layout.addWidget(QLabel("Field"), 0, 2)
        self.osf_condition_rows_layout.addWidget(QLabel("Search Term"), 0, 3)
        self.osf_condition_rows_layout.setColumnStretch(3, 1)

        cond_layout.addWidget(self.osf_condition_rows_widget)

        btn_layout = QHBoxLayout()
        self.osf_add_condition_button = QPushButton("➕ Add Term")
        self.osf_remove_condition_button = QPushButton("➖ Remove Term")
        self.osf_add_condition_button.clicked.connect(self.add_osf_condition_row)
        self.osf_remove_condition_button.clicked.connect(self.remove_osf_condition_row)
        btn_layout.addWidget(self.osf_add_condition_button)
        btn_layout.addWidget(self.osf_remove_condition_button)
        btn_layout.addStretch()
        cond_layout.addLayout(btn_layout)
        cond_group.setLayout(cond_layout)
        build_layout.addWidget(cond_group)

        self.osf_condition_rows = []
        self.add_osf_condition_row()

        # Free text / paste tab
        free_layout = QVBoxLayout(self.osf_free_tab)
        group = QGroupBox("OSF Free Text Query")
        g_l = QVBoxLayout()
        info = QLabel("?")
        info.setStyleSheet(self.info_style)
        info.setToolTip("Enter search terms. OSF API searches titles only; Weblike uses titles, abstracts, and keywords.")
        self.osf_query_input = QTextEdit()
        self.osf_query_input.setMaximumHeight(80)
        self.osf_query_input.setPlaceholderText("e.g. cognitive therapy AND depression")
        g_l.addWidget(info)
        g_l.addWidget(self.osf_query_input)
        group.setLayout(g_l)
        free_layout.addWidget(group)

    def add_condition_row(self):
        row_index = len(self.condition_rows) + 1
        op = QComboBox()
        op.addItems(["AND", "OR"])
        if len(self.condition_rows) == 0:
            op.setEnabled(False)
        field = QComboBox()
        field.addItems(SERVERS.get("ArXiv", {}).get("fields", ["all"]))
        value = QLineEdit()
        value.setPlaceholderText("Enter search term...")
        self.condition_rows_layout.addWidget(QLabel(f"{len(self.condition_rows) + 1}."), row_index, 0)
        self.condition_rows_layout.addWidget(op, row_index, 1)
        self.condition_rows_layout.addWidget(field, row_index, 2)
        self.condition_rows_layout.addWidget(value, row_index, 3)
        self.condition_rows.append({"operator": op, "field": field, "value": value})

    def remove_condition_row(self):
        if not self.condition_rows:
            return
        last = self.condition_rows.pop()
        last["operator"].deleteLater()
        last["field"].deleteLater()
        last["value"].deleteLater()
        for i in reversed(range(self.condition_rows_layout.count())):
            w = self.condition_rows_layout.itemAt(i).widget()
            if isinstance(w, QLabel) and w.text() == f"{len(self.condition_rows) + 1}.":
                w.deleteLater()
                break

    def add_osf_condition_row(self):
        row_index = len(self.osf_condition_rows) + 1
        op = QComboBox()
        op.addItems(["AND", "OR"])
        if len(self.osf_condition_rows) == 0:
            op.setEnabled(False)
        # use OSF-specific fields if present in config, otherwise sensible defaults
        field = QComboBox()
        field.addItems(SERVERS.get("OSF", {}).get("fields", ["title", "abstract", "keywords"]))
        value = QLineEdit()
        value.setPlaceholderText("Enter search term...")
        self.osf_condition_rows_layout.addWidget(QLabel(f"{len(self.osf_condition_rows) + 1}."), row_index, 0)
        self.osf_condition_rows_layout.addWidget(op, row_index, 1)
        self.osf_condition_rows_layout.addWidget(field, row_index, 2)
        self.osf_condition_rows_layout.addWidget(value, row_index, 3)
        self.osf_condition_rows.append({"operator": op, "field": field, "value": value})

    def remove_osf_condition_row(self):
        if not self.osf_condition_rows:
            return
        last = self.osf_condition_rows.pop()
        last["operator"].deleteLater()
        last["field"].deleteLater()
        last["value"].deleteLater()
        for i in reversed(range(self.osf_condition_rows_layout.count())):
            w = self.osf_condition_rows_layout.itemAt(i).widget()
            if isinstance(w, QLabel) and w.text() == f"{len(self.osf_condition_rows) + 1}.":
                w.deleteLater()
                break

    def server_changed(self, server_name):
        self.current_server = server_name
        server_config = SERVERS.get(server_name, {"type": "arxiv"})
    
        if server_config.get("type") == "arxiv":
            # ArXiv mode
            self.strategy_label.setVisible(False)
            self.strategy_info.setVisible(False)
            self.standard_radio.setVisible(False)
            self.comprehensive_radio.setVisible(False)
            # arXiv tabs: Build, Paste Query, Paste URL visible; OSF tab hidden
            self.tabs.setTabVisible(0, True)
            self.tabs.setTabVisible(1, True)
            self.tabs.setTabVisible(2, True)
            self.tabs.setTabVisible(3, False)
            self.tabs.setCurrentIndex(0)
            # preview useful for build query; keep visible for Build Query
            self.preview_button.setVisible(True)
            self.osf_repo_widget.setVisible(False)
    
        elif server_config.get("type") == "osf":
            # OSF mode (multi-server)
            self.strategy_label.setVisible(True)
            self.strategy_info.setVisible(True)
            self.standard_radio.setVisible(True)
            self.comprehensive_radio.setVisible(True)
            # Only show OSF tab
            self.tabs.setTabVisible(0, False)
            self.tabs.setTabVisible(1, False)
            self.tabs.setTabVisible(2, False)
            self.tabs.setTabVisible(3, True)
            self.tabs.setCurrentIndex(3)
            self.preview_button.setVisible(False)
            self.osf_repo_widget.setVisible(True)


    def run_scraper(self):
        server_config = SERVERS.get(self.current_server, {"type": "arxiv"})
        base_filename = self.filename_input.text().strip() or "OASIS_search"
        politeness = self.politeness_combo.currentText()

        # Clear feedback
        self.feedback_text.clear()

        # UI state changes
        self.run_button.setEnabled(False)
        self.run_button.setText(" Searching...")
        self.abort_button.setEnabled(True)

        try:
            if server_config["type"] == "arxiv":
                # ArXiv mode
                # Tab indices: 0 = Build Query, 1 = Paste Query, 2 = Paste URL
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
                        self._reset_run_button()
                        return

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

                elif self.tabs.currentIndex() == 1:  # Paste Query (raw query string)
                    query = self.paste_query_text.toPlainText().strip()
                    if not query:
                        QMessageBox.warning(self, "Input Error", "Please paste a valid ArXiv query.")
                        self._reset_run_button()
                        return
                    logging.info(f"Starting ArXiv Paste Query search. Query: {query}")
                    self.scraper_thread = ScraperThread(
                        server_config=server_config,
                        query=query,
                        search_mode="paste_query",
                        conditions=None,
                        url=None,
                        politeness=politeness
                    )

                else:  # Paste URL tab (index 2)
                    url = self.paste_url_text.toPlainText().strip()
                    if not url:
                        QMessageBox.warning(self, "Input Error", "Please paste a valid ArXiv search URL.")
                        self._reset_run_button()
                        return
                    url = re.sub(r"size=\d+", f"size={200}", url)
                    if "order=" in url:
                        url = re.sub(r"order=[^&]+", f"order={'-announced_date_first'}", url)
                    else:
                        url += f"&order={'-announced_date_first'}"
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

                # connect signals
                self.scraper_thread.progress.connect(self.update_progress)
                self.scraper_thread.finished.connect(self.scraper_finished)
                self.scraper_thread.error.connect(self.scraper_error)
                self.scraper_thread.start()

            else:
                # OSF mode (multi-provider support)
                # Determine if using build query or free text
                use_build = (self.osf_inner_tabs.currentIndex() == 0)
                if use_build:
                    conditions = []
                    for row in self.osf_condition_rows:
                        field = row['field'].currentText()
                        operator = row['operator'].currentText() if row['operator'].isEnabled() else "AND"
                        value = row['value'].text().strip()
                        if value:
                            conditions.append({'field': field, 'operator': operator, 'value': value})
                    if not conditions:
                        QMessageBox.warning(self, "Input Error", "Add at least one OSF search term.")
                        self._reset_run_button()
                        return
                    search_mode = "build_query"
                    query_payload = conditions  # pass conditions
                else:
                    query = self.osf_query_input.toPlainText().strip()
                    if not query:
                        QMessageBox.warning(self, "Input Error", "Please enter search terms.")
                        self._reset_run_button()
                        return
                    search_mode = "api" if self.standard_radio.isChecked() else "weblike"
                    query_payload = query

                selected_providers = [cb.text()
                                      for cb in self.osf_server_checks
                                      if cb.isChecked()]
                if not selected_providers:
                    QMessageBox.warning(self, "Input Error", "Select at least one OSF server.")
                    self._reset_run_button()
                    return

                # run sequential searches for each selected provider
                self.all_results = pd.DataFrame()
                for prov_name in selected_providers:
                    prov_config = SERVERS.get(prov_name)
                    logging.info(f"Starting OSF search on provider={prov_name}, mode={search_mode}")
                    self.feedback_text.append(f"\n🔍 Searching {prov_name}...\n")
                    # pass conditions when build_query, else pass string query
                    kwargs = dict(server_config=prov_config, query=query_payload, search_mode=search_mode, politeness=politeness)
                    if use_build:
                        kwargs["conditions"] = query_payload
                    worker = ScraperThread(**kwargs)
                    # connect ephemeral signals synchronously via blocking run in thread
                    worker.progress.connect(self.update_progress)
                    worker.finished.connect(lambda df, p=prov_name: self._collect_and_continue(df, p, base_filename, search_mode))
                    worker.error.connect(self.scraper_error)
                    worker.start()
                    # wait for the worker to finish before continuing (sequential)
                    worker.wait()

                # after loop, results have been saved by _collect_and_continue
        except Exception as e:
            self.scraper_error(str(e))

    def _collect_and_continue(self, df, provider_name, base_filename, search_mode):
        # merge into master dataframe
        if df is not None and not df.empty:
            if not hasattr(self, "all_results") or self.all_results is None:
                self.all_results = df
            else:
                self.all_results = pd.concat([self.all_results, df], ignore_index=True)
            self.feedback_text.append(f"✅ {len(df)} results from {provider_name}")

        # if this method is invoked after the last provider, save file
        # Note: we don't know which provider is last here, so caller saves after loop in run_scraper.
        # Save is handled after run loop: do quick check and save if present
        if hasattr(self, "all_results") and not self.all_results.empty:
            filename = os.path.join("data", f"{base_filename}_{provider_name}_{'OSF_API' if self.standard_radio.isChecked() else 'weblike'}.csv")
            unique = unique_filename(filename)
            self.all_results.to_csv(unique, index=False)
            msg = f"\nSearch complete. {len(self.all_results)} preprints saved to '{unique}'"
            self.feedback_text.append(msg)
            logging.info(msg)
            QMessageBox.information(self, "Search Complete", f"Successfully collected {len(self.all_results)} preprints.\n\nFile saved as: {unique}\nLog file: {self.log_filename}")
            # reset UI
            self._reset_run_button()

    def _reset_run_button(self):
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
        self.feedback_text.append(message)
        logging.info(message)

    def scraper_finished(self, df):
        logging.info(f"Search completed successfully on server={self.current_server}, results={len(df)}")
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

        unique = unique_filename(filename)
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
            f"&size={200}"
            f"&order={'-announced_date_first'}"
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