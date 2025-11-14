# Entrypoint for OASIS application
import sys
import os
from PyQt6.QtWidgets import QApplication, QMainWindow
from .ui_main import OASISWidget

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    window = QMainWindow()
    oasis_widget = OASISWidget()
    window.setCentralWidget(oasis_widget)
    window.setWindowTitle("OASIS - Open ArXiv Scraper")
    window.resize(710, 600)
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
