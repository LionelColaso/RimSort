from pathlib import Path
from PySide6.QtGui import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QWidget, QVBoxLayout

from app.utils.steam.steamcmd.wrapper import SteamcmdInterface


class Acf_Reader(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.acf_path_str = SteamcmdInterface.instance().steamcmd_appworkshop_acf_path

        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowTitle("Update Log")
        self.setObjectName("acf_reader")

        layout = QVBoxLayout()
        self.setLayout(layout)

        table = QTableWidget()
        table.setRowCount(0)
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["pfid", "size", "timeupdated", "manifest"])
        table.horizontalHeader().setStretchLastSection(True)

        if self.acf_path_str:
            acf_path = Path(self.acf_path_str)
            if acf_path.exists():
                self.populate_table(table, acf_path)
            else:
                table.setRowCount(1)
                table.setItem(0, 0, QTableWidgetItem(f"File not found: {acf_path}"))
        else:
            table.setRowCount(1)
            table.setItem(0, 0, QTableWidgetItem("ACF path not provided"))

        layout.addWidget(table)

    def populate_table(self, table, acf_path):
        acf_data = self.read_acf_file(acf_path)

        for pfid, data in acf_data.items():
            row_position = table.rowCount()
            table.insertRow(row_position)
            table.setItem(row_position, 0, QTableWidgetItem(f'"{pfid}"'))
            table.setItem(
                row_position, 1, QTableWidgetItem(f'"{data.get("size", "")}"')
            )
            table.setItem(
                row_position, 2, QTableWidgetItem(f'"{data.get("timeupdated", "")}"')
            )
            table.setItem(
                row_position, 3, QTableWidgetItem(f'"{data.get("manifest", "")}"')
            )

    def read_acf_file(self, acf_path):
        acf_data = {}
        with open(acf_path, "r", encoding="utf-8") as file:
            lines = file.readlines()

        in_workshop_items_installed = False
        current_pfid = None
        current_data = {}
        for line in lines:
            line = line.strip()
            if line == '"WorkshopItemsInstalled"':
                in_workshop_items_installed = True
                continue
            elif line == "}":
                in_workshop_items_installed = False
                if current_pfid:
                    acf_data[current_pfid] = current_data
                    current_data = {}
                continue

            if in_workshop_items_installed:
                if line.startswith('"'):
                    if current_pfid:
                        acf_data[current_pfid] = current_data
                        current_data = {}
                    current_pfid = line.strip('"')
                elif line.startswith('\t\t"'):
                    line = line.strip("\t")
                    key_value = line.split('"')
                    if len(key_value) >= 3:
                        key = key_value[1].strip()
                        value = key_value[2].strip()
                        current_data[key] = value

        return acf_data
