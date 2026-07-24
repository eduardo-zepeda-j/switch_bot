"""Lanza la interfaz gráfica de Switch_bot (standalone, sin Coordinator)."""

import sys

from PyQt6.QtWidgets import QApplication

from switch_bot.gui import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
