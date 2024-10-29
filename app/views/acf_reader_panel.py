import logging
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from app.utils.steam.steamcmd.wrapper import SteamcmdInterface


class AcfReaderThread(QThread):
    """
    A QThread class to read the ACF file in a separate thread to avoid blocking the UI.
    Emits a signal with the parsed ACF data when the reading is complete.
    """

    # Corrected signal definition with argument type
    data_ready = Signal(Dict[str, Dict[str, Any]])  # Signal to emit the parsed ACF data

    def __init__(self, acf_path: Path) -> None:
        """
        Initialize the thread with the path to the ACF file.

        Args:
            acf_path (Path): Path to the ACF file to be read.
        """
        super().__init__()
        self.acf_path = acf_path

    def run(self) -> None:
        """
        Main thread execution method. Reads the ACF file and emits the parsed data.
        """
        try:
            acf_data = self.read_acf_file(self.acf_path)
            self.data_ready.emit(acf_data)  # Emit the parsed data
        except Exception as e:
            logging.error(f"Error reading ACF file: {e}")
            self.data_ready.emit({})  # Emit empty dict on error

    def read_acf_file(self, acf_path: Path) -> Dict[str, Dict[str, Any]]:
        """
        Read the ACF file and parse its contents into a dictionary.

        Args:
            acf_path (Path): Path to the ACF file.

        Returns:
            Dict[str, Dict[str, Any]]: Parsed ACF data in dictionary format.
        """
        acf_data: Dict[str, Dict[str, Any]] = {}
        current_pfid: Optional[str] = None
        current_data: Dict[str, Any] = {}
        in_workshop_items_installed: bool = False
        in_workshop_item_details: bool = False

        try:
            with acf_path.open("r") as file:
                for line in file:
                    line = line.strip()
                    self.process_line(
                        line,
                        acf_data,
                        current_pfid,
                        current_data,
                        in_workshop_items_installed,
                        in_workshop_item_details,
                    )
        except IOError as e:
            logging.error(f"Failed to open ACF file: {e}")
            return {}

        return acf_data

    def process_line(
        self,
        line: str,
        acf_data: Dict[str, Dict[str, Any]],
        current_pfid: Optional[str],
        current_data: Dict[str, Any],
        in_workshop_items_installed: bool,
        in_workshop_item_details: bool,
    ) -> None:
        """
        Process a single line from the ACF file.

        Args:
            line (str): The current line being processed.
            acf_data (Dict): The dictionary to store parsed data.
            current_pfid (Optional[str]): The current pfid being processed.
            current_data (Dict): The data associated with the current pfid.
            in_workshop_items_installed (bool): Flag indicating if we are in the "WorkshopItemsInstalled" section.
            in_workshop_item_details (bool): Flag indicating if we are in the "WorkshopItemDetails" section.
        """
        if line == '"WorkshopItemsInstalled"':
            in_workshop_items_installed = True
        elif line == '"WorkshopItemDetails"':
            in_workshop_item_details = True
        elif line == "}":
            self.end_section(acf_data, current_pfid, current_data)
            in_workshop_items_installed = False
            in_workshop_item_details = False
        elif in_workshop_items_installed or in_workshop_item_details:
            self.process_data_line(line, acf_data, current_pfid, current_data)

    def end_section(
        self,
        acf_data: Dict[str, Dict[str, Any]],
        current_pfid: Optional[str],
        current_data: Dict[str, Any],
    ) -> None:
        """
        Finalize the current section and store the parsed data.

        Args:
            acf_data (Dict[str, Dict[str, Any]]): The dictionary to store parsed data.
            current_pfid (Optional[str]): The current pfid being processed.
            current_data (Dict[str, Any]): The data associated with the current pfid.
        """
        if current_pfid and current_data:
            acf_data[current_pfid] = current_data

    def process_data_line(
        self,
        line: str,
        acf_data: Dict[str, Dict[str, Any]],
        current_pfid: Optional[str],
        current_data: Dict[str, Any],
    ) -> None:
        """
        Process a line containing key-value pairs.

        Args:
            line (str): The current line being processed.
            acf_data (Dict[str, Dict[str, Any]]): The dictionary to store parsed data.
            current_pfid (Optional[str]): The current pfid being processed.
            current_data (Dict[str, Any]): The data associated with the current pfid.
        """
        if line.startswith('"'):
            self.start_new_pfid(line, acf_data, current_pfid, current_data)
        elif line.startswith('\t\t"'):
            self.add_key_value_pair(line, current_data)

    def start_new_pfid(
        self,
        line: str,
        acf_data: Dict[str, Dict[str, Any]],
        current_pfid: Optional[str],
        current_data: Dict[str, Any],
    ) -> None:
        """
        Start processing a new pfid.

        Args:
            line (str): The line containing the new pfid.
            acf_data (Dict[str, Dict[str, Any]]): The dictionary to store parsed data.
            current_pfid (Optional[str]): The current pfid being processed.
            current_data (Dict[str, Any]): The data associated with the current pfid.
        """
        if current_pfid:
            acf_data[current_pfid] = current_data
        current_pfid = line.strip('"')
        current_data.clear()  # Clear current data for new pfid

    def add_key_value_pair(self, line: str, current_data: Dict[str, Any]) -> None:
        """
        Add a key-value pair to the current pfid's data.

        Args:
            line (str): The line containing the key-value pair.
            current_data (Dict[str, Any]): The data associated with the current pfid.
        """
        line = line.strip("\t")
        key_value = line.split('"', 2)
        key = key_value[1]
        value = key_value[2].strip()
        current_data[key] = value


class AcfReader(QWidget):
    """
    A QWidget class to display ACF data in a table format.
    Reads ACF data from a file and populates a QTableWidget.
    """

    def __init__(self) -> None:
        """
        Initialize the AcfReader widget and set up the UI components.
        """
        super().__init__()

        # Set up logging
        self.logger = logging.getLogger(self.__class__.__name__)

        # Initialize ACF path from SteamcmdInterface
        self.acf_path_str: Optional[str] = (
            SteamcmdInterface.instance().steamcmd_appworkshop_acf_path
        )

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
        self.table.setSortingEnabled(True)  # Enable sorting
        self.table.resizeColumnsToContents()  # Resize columns to fit content

        # Populate the table with ACF data
        self.populate_table()

        # Add table to layout
        layout.addWidget(self.table)

    def populate_table(self) -> None:
        """
        Populate the table with data from the ACF file.
        If the ACF path is invalid or the file does not exist, an error message is displayed.
        """
        if self.acf_path_str:
            acf_path = Path(self.acf_path_str)
            if acf_path.exists():
                # Start a thread to read the ACF file
                self.acf_reader_thread = AcfReaderThread(acf_path)
                self.acf_reader_thread.data_ready.connect(self.fill_table)
                self.acf_reader_thread.start()
            else:
                self.display_error(f"File not found: {acf_path}")
        else:
            self.display_error("ACF path not provided")

    def fill_table(self, acf_data: Dict[str, Dict[str, Any]]) -> None:
        """
        Fill the table with ACF data.

        Args:
            acf_data (Dict[str, Dict[str, Any]]): The parsed ACF data.
        """
        self.table.setRowCount(0)  # Clear existing rows
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
        """
        Display an error message in the table.

        Args:
            message (str): The error message to display.
        """
        self.table.setRowCount(1)  # Clear existing rows
        self.table.setItem(0, 0, QTableWidgetItem(message))  # Display the error message
