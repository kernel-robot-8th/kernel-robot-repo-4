import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# On Python 3.10, PySide6 injects a placeholder typing.Self; importing typing_extensions first keeps
# its own Self so torch (imported lazily via lerobot) does not fail with "Plain typing.Self ...".
import typing_extensions  # noqa: E402, F401

from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.main_window import MainWindow  # noqa: E402


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
