from PySide6.QtGui import Qt
from PySide6.QtWidgets import QWidget


class Acf_Reader(QWidget):

    def __init__(self) -> None:
        super().__init__()

        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        self.setWindowTitle("Update Log")
        self.setObjectName("acf_reader")
