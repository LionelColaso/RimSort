from pathlib import Path
from typing import Any, Dict

from PySide6.QtGui import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from app.utils.steam.steamcmd.wrapper import SteamcmdInterface


class Acf_Reader(QWidget):
    def __init__(self) -> None:
        super().__init__()

        # Initialize ACF path from SteamcmdInterface
        self.acf_path_str = SteamcmdInterface.instance().steamcmd_appworkshop_acf_path

        # Set up the widget properties
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowTitle("Update Log")
        self.setObjectName("acf_reader")

        # Create layout and table
        layout = QVBoxLayout()
        self.setLayout(layout)

        self.table = QTableWidget()
        self.table.setRowCount(0)
        self.table.setColumnCount(6)  # Adjusted for additional columns
        self.table.setHorizontalHeaderLabels(
            [
                "pfid",
                "size",
                "timeupdated",
                "manifest",
                "timetouched",
                "latest_manifest",
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(True)

        # Populate the table with ACF data
        self.populate_table()

        # Add table to layout
        layout.addWidget(self.table)

    def populate_table(self) -> None:
        """Populate the table with data from the ACF file."""
        if self.acf_path_str:
            acf_path = Path(self.acf_path_str)
            if acf_path.exists():
                acf_data = self.read_acf_file(acf_path)
                self.fill_table(acf_data)
            else:
                self.display_error(f"File not found: {acf_path}")
        else:
            self.display_error("ACF path not provided")

    def fill_table(self, acf_data: Dict[str, Dict[str, Any]]) -> None:
        """Fill the table with ACF data."""
        for pfid, details in acf_data.items():
            row_position = self.table.rowCount()
            self.table.insertRow(row_position)
            self.table.setItem(row_position, 0, QTableWidgetItem(pfid))
            self.table.setItem(
                row_position, 1, QTableWidgetItem(str(details.get("size", "")))
            )
            self.table.setItem(
                row_position, 2, QTableWidgetItem(str(details.get("timeupdated", "")))
            )
            self.table.setItem(
                row_position, 3, QTableWidgetItem(str(details.get("manifest", "")))
            )
            self.table.setItem(
                row_position, 4, QTableWidgetItem(str(details.get("timetouched", "")))
            )
            self.table.setItem(
                row_position,
                5,
                QTableWidgetItem(str(details.get("latest_manifest", ""))),
            )

    def display_error(self, message: str) -> None:
        """Display an error message in the table."""
        self.table.setRowCount(1)
        self.table.setItem(0, 0, QTableWidgetItem(message))

    def read_acf_file(self, acf_path: Path) -> Dict[str, Dict[str, Any]]:
        """Read the ACF file and return its contents as a dictionary."""
        acf_data = {}
        current_pfid = None
        current_data = {}
        in_workshop_items_installed = False
        in_workshop_item_details = False

        with acf_path.open("r") as file:
            for line in file:
                line = line.strip()

                # Detect sections
                if line == '"WorkshopItemsInstalled"':
                    in_workshop_items_installed = True
                    continue
                elif line == '"WorkshopItemDetails"':
                    in_workshop_item_details = True
                    continue
                elif line == "}":
                    # End of a section
                    if current_pfid and current_data:
                        acf_data[current_pfid] = current_data
                    current_pfid = None
                    current_data = {}
                    in_workshop_items_installed = False
                    in_workshop_item_details = False
                    continue

                if in_workshop_items_installed or in_workshop_item_details:
                    if line.startswith('"'):
                        if current_pfid:
                            # If we are already in a pfid, store the current data
                            if current_pfid not in acf_data:
                                acf_data[current_pfid] = {}
                            acf_data[current_pfid].update(current_data)
                        current_pfid = line.strip('"')
                        current_data = {}  # Reset for new pfid
                    elif line.startswith('\t\t"'):
                        line = line.strip("\t")
                        key_value = line.split('"', 2)
                        key = key_value[1]
                        value = key_value[2].strip()
                        current_data[key] = value

        return acf_data
