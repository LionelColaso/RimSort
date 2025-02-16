import concurrent.futures
import os
import sys
import time
from functools import lru_cache
from pathlib import Path
from tempfile import gettempdir
from typing import Dict, List, Optional

from loguru import logger
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.controllers.settings_controller import SettingsController
from app.utils import metadata
from app.views.dialogue import show_warning
from app.views.mods_panel import ModsPanel


class ProgressWindow(QWidget):
    """
    A window that displays search progress information including:
    - Current progress percentage
    - Current file Path being processed
    - Total number of files found

    Attributes:
        progress_label (QLabel): Displays the current progress percentage
        current_file_label (QLabel): Shows the current file being processed
        files_to_search_count_label (QLabel): Displays total files found
    """

    def __init__(self) -> None:
        """Initialize the enhanced progress window."""
        super().__init__()
        self.setWindowTitle("Search Progress")
        self.setFixedSize(400, 200)

        # Main layout
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Progress tracking
        self._setup_progress_tracking(layout)

        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.close)
        layout.addWidget(self.cancel_button)

        self.setLayout(layout)

    def _setup_progress_tracking(self, layout: QVBoxLayout) -> None:
        """Setup progress bar and related status labels."""
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        self.status_layout = QVBoxLayout()
        self.status_layout.setSpacing(5)

        self.current_file_label = QLabel("Current File: ")
        self.files_found_label = QLabel("Files Found: 0")
        self.processing_label = QLabel("Processing: 0%")

        self.status_layout.addWidget(self.current_file_label)
        self.status_layout.addWidget(self.files_found_label)
        self.status_layout.addWidget(self.processing_label)
        layout.addLayout(self.status_layout)

    def update_progress(self, value: int) -> None:
        """Update the progress percentage."""
        self.progress_bar.setValue(value)
        self.processing_label.setText(f"Processing: {value}%")

    def update_current_file(self, file_path: str) -> None:
        """Update the current file being processed."""
        self.current_file_label.setText(f"Current File: {Path(file_path).name}")

    def update_file_count(self, count: int) -> None:
        """Update the total number of files found."""
        self.files_found_label.setText(f"Files Found: {count}")

    def reset(self) -> None:
        """Reset all progress indicators."""
        self.progress_bar.reset()
        self.current_file_label.setText("Current File: ")
        self.files_found_label.setText("Files Found: 0")
        self.processing_label.setText("Processing: 0%")


class SearchThread(QThread):
    """
    A thread for performing file and folder searches in the background.

    Attributes:
        settings_controller (SettingsController): Controller for application settings
        search_text (str): The text to search for
        search_options (Dict[str, bool | str]): Dictionary of search options
        search_path (str): Path to search in
        search_tool (SearchTool): Reference to the search tool instance
        mods_panel (ModsPanel): Panel for managing mods
        metadata_manager (MetadataManager): Manager for mod metadata

    Emits:
        search_result (Signal): Emits search results as strings
        search_progress (Signal): Emits progress as integers (0-100)
        current_file (Signal): Emits the current file being processed
        file_count (Signal): Emits the total number of files found
    """

    search_tool: "SearchTool"  # Add type hint for search_tool

    search_result = Signal(str)
    search_progress = Signal(int)
    current_file = Signal(str)
    file_count = Signal(int)

    def __init__(
        self,
        settings_controller: SettingsController,
        search_text: str,
        search_options: Dict[str, bool | str],
        search_path: str,
        search_tool: "SearchTool",
    ) -> None:
        self.settings_controller = settings_controller
        self.search_tool = search_tool
        super().__init__()

        self.search_text = (
            search_text.lower()
            if not search_options.get("case_sensitive")
            else search_text
        )
        self.search_options: Dict[str, bool | str] = search_options
        self.search_path = search_path

        self.mods_panel = ModsPanel(
            settings_controller=self.settings_controller,
        )
        self.metadata_manager = metadata.MetadataManager.instance()

    def _validate_search_path(self) -> bool:
        """Validate the search path and show warning if invalid."""
        if not self.search_path:
            logger.warning("No valid search path provided.")
            self.search_result.emit("No valid search path provided.")
            show_warning("No valid search path provided.")
            return False
        return True

    def _get_search_folder(self) -> str:
        """Get the folder to search from search options."""
        return str(self.search_options.get("folder", self.search_path))

    @lru_cache(maxsize=128)
    def _count_total_files(self, folder: str) -> int:
        """Count total files in the search folder with caching."""
        return sum(len(files) for _, _, files in os.walk(folder))

    def _process_file(self, file: str, root: str, count: int) -> int:
        """
        Process a single file and check if it matches search criteria.
        Skips large binary files and uses memory mapping for efficient reading.

        Returns:
            int: Updated count of matching files
        """
        file_path = os.path.join(root, file)
        self.current_file.emit(file_path)

        # Skip files larger than 10MB
        file_size = os.path.getsize(file_path)
        if file_size > 10 * 1024 * 1024:  # 10MB
            logger.debug(f"Skipping large file: {file_path} ({file_size} bytes)")
            return count

        if self.search_tool.check_search_criteria(file, file_path):
            count += 1
            logger.debug(f"Processing file: {file_path}")
            self.search_result.emit(file_path)
        return count

    def _process_directory(self, folder: str, exclude_folders: List[str]) -> int:
        """
        Process all files in a directory and its subdirectories using parallel processing.

        Args:
            folder (str): Path to the folder to search
            exclude_folders (List[str]): List of folder names to exclude

        Returns:
            int: Total number of matching files found

        Raises:
            OSError: If there's an error accessing the directory
            Exception: For any unexpected errors during processing
        """
        try:
            count = 0
            total_files = self._count_total_files(folder)
            self.file_count.emit(total_files)

            if total_files == 0:
                logger.warning("No files found in the specified folder.")
                self.search_result.emit("No files found.")
                return 0

            # Collect all files to process
            files_to_process: List[tuple[str, str]] = []
            for root, dirs, files in os.walk(folder):
                if self.isInterruptionRequested():
                    return count
                dirs[:] = [d for d in dirs if d not in exclude_folders]
                files_to_process.extend((file, root) for file in files)

            # Process files in parallel
            with concurrent.futures.ThreadPoolExecutor() as executor:
                # Convert set to list for predictable iteration order
                futures = [
                    executor.submit(self._process_file, file, root, 0)
                    for file, root in files_to_process
                ]

                completed = 0
                total = len(futures)
                for future in concurrent.futures.as_completed(futures):
                    if self.isInterruptionRequested():
                        return count
                    try:
                        count += future.result()
                        completed += 1
                        progress = int((completed / total) * 100)
                        self.search_progress.emit(progress)
                    except Exception as e:
                        logger.error(f"Error processing file: {e}")
                        continue

            return count
        except Exception as e:
            logger.error(f"Unexpected error during directory processing: {e}")
            self.search_result.emit(f"Unexpected error: {str(e)}")
            raise

    def run(self) -> None:
        """Execute the search process, iterating through files and folders."""
        if not self._validate_search_path():
            return

        folder = self._get_search_folder()
        exclude_folders = self.get_exclude_folders()
        count = self._process_directory(folder, exclude_folders)

        self.search_result.emit(f"Total Results: {count} files found.")

    def get_exclude_folders(self) -> List[str]:
        """
        Determine which folders to exclude from the search.
        """
        exclude_folders: List[str] = []
        if not self.search_options.get("include_git"):
            exclude_folders.append(".git")
        if not self.search_options.get("include_languages"):
            exclude_folders.extend(["Languages", "languages"])
        if not self.search_options.get("include_source"):
            exclude_folders.extend(["Source", "source"])
        return exclude_folders


class SearchTool(QMainWindow):
    """
    Main application window for the file search tool.

    Attributes:
        settings_controller (SettingsController): Controller for application settings
        search_thread (Optional[SearchThread]): Background search thread
        mods_panel (ModsPanel): Panel for managing mods
        metadata_manager (MetadataManager): Manager for mod metadata
        search_txt_path (str): Path to temporary search text file
        progress_window (ProgressWindow): Window showing search progress
        search_results_table (QTableWidget): Table displaying search results
        folder_path_label (QLabel): Label showing selected folder path
        search_text (QLineEdit): Input field for search text
        mod_select_combo (QComboBox): Dropdown for mod selection
        search_type_combo (QComboBox): Dropdown for search type
        case_sensitive_check (QCheckBox): Checkbox for case sensitivity
        include_git_check (QCheckBox): Checkbox for including .git folders
        include_languages_check (QCheckBox): Checkbox for including Languages folders
        include_source_check (QCheckBox): Checkbox for including Source folders
        search_button (QPushButton): Button to start search
        stop_button (QPushButton): Button to stop search
        clear_button (QPushButton): Button to clear results
        save_results_button (QPushButton): Button to save results
    """

    def __init__(self, settings_controller: SettingsController) -> None:
        super().__init__()
        self.settings_controller = settings_controller
        self.search_thread: Optional[SearchThread] = None
        self.mods_panel: ModsPanel = ModsPanel(
            settings_controller=self.settings_controller,
        )
        self.search_options: Dict[str, bool | str] = {}

        self.metadata_manager: metadata.MetadataManager = (
            metadata.MetadataManager.instance()
        )
        self.search_txt_path: str = str((Path(gettempdir()) / "search.txt"))

        self.setWindowTitle("File Search")
        self.setMinimumSize(800, 600)

        main_widget = QWidget()
        layout = QVBoxLayout(main_widget)

        # Setup UI components
        self._setup_folder_selection(layout)

        # Create horizontal layout for search input and mod selection
        search_row = QHBoxLayout()
        self._setup_search_input(search_row)
        self._setup_mod_select(search_row)
        self._setup_search_type_combo(search_row)
        layout.addLayout(search_row)

        self._setup_search_options(layout)
        self._setup_buttons(layout)
        self._setup_extension_buttons(layout)

        # Initialize progress window
        self.progress_window = ProgressWindow()
        self.progress_window.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowCloseButtonHint
        )

        # Initialize loading bar
        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)  # Indeterminate mode
        self.loading_bar.setVisible(False)
        layout.addWidget(self.loading_bar)
        layout.addWidget(self.progress_window)

        self.search_results_table = QTableWidget()

        self.search_results_table.setColumnCount(3)

        # Add progress and file info widgets
        self.file_count_label = QLabel(
            f"Files Match Found: {self.search_results_table.rowCount()}"
        )

        file_info_layout = QHBoxLayout()
        # file_info_layout.addWidget(self.current_file_label)
        file_info_layout.addWidget(self.file_count_label)
        layout.addLayout(file_info_layout)

        # Set column headers
        self.search_results_table.setHorizontalHeaderLabels(
            ["Mod Name", "File Name", "File Path"]
        )

        # Configure table resizing
        header = self.search_results_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self.search_results_table)
        self.setCentralWidget(main_widget)

        # Generate search path after UI is initialized
        self._generate_search_path()

    def _setup_folder_selection(self, layout: QVBoxLayout) -> None:
        folder_layout = QHBoxLayout()
        self.folder_path_label = QLabel()
        folder_layout.addWidget(self.folder_path_label)
        layout.addLayout(folder_layout)

    def _setup_search_input(self, layout: QHBoxLayout) -> None:
        self.search_text = QLineEdit()
        self.search_text.setPlaceholderText("Enter search text")
        self.search_text.setToolTip("Type the text you want to search for in files.")
        self.search_text.returnPressed.connect(self.start_search)
        layout.addWidget(self.search_text, stretch=3)

    def _setup_mod_select(self, layout: QHBoxLayout) -> None:
        self.mod_select_combo = QComboBox()
        self.mod_select_combo.addItems(["All Mods", "Active Mods"])
        self.mod_select_combo.currentTextChanged.connect(self._generate_search_path)
        layout.addWidget(self.mod_select_combo, stretch=1)

    def _setup_search_type_combo(self, layout: QHBoxLayout) -> None:
        self.search_type_combo = QComboBox()
        self.search_type_combo.addItems(
            ["File and Folder Names", "Inside All Files", ".xml Extensions Only"]
        )
        self.search_type_combo.setCurrentIndex(2)
        layout.addWidget(self.search_type_combo, stretch=1)

    def _setup_search_options(self, layout: QVBoxLayout) -> None:
        options_layout = QHBoxLayout()
        self.case_sensitive_check = QCheckBox("Case Sensitive")
        self.include_git_check = QCheckBox("Include .git Folders")
        self.include_languages_check = QCheckBox("Include Languages Folders")
        self.include_source_check = QCheckBox("Include Source Folders")

        for button in [
            self.case_sensitive_check,
            self.include_git_check,
            self.include_languages_check,
            self.include_source_check,
        ]:
            options_layout.addWidget(button)
        layout.addLayout(options_layout)

    def _setup_buttons(self, layout: QVBoxLayout) -> None:
        button_layout = QHBoxLayout()

        self.search_button = QPushButton("Search")
        self.search_button.setToolTip(
            "Start searching for files matching your criteria.\n"
            "Supports searching by file name, content, and extensions."
        )

        self.stop_button = QPushButton("Stop")
        self.stop_button.setToolTip(
            "Stop the current search operation.\nAny partial results will be preserved."
        )

        self.clear_button = QPushButton("Clear")
        self.clear_button.setToolTip(
            "Clear all search results and reset the search interface.\n"
            "This does not affect the search history or saved results."
        )

        self.save_results_button = QPushButton("Save Results to .txt")
        self.save_results_button.setToolTip(
            "Save the current search results to a text file.\n"
            "The file will include mod names, file names, and full paths."
        )

        self.search_button.clicked.connect(self.start_search)
        self.stop_button.clicked.connect(self.stop_search)
        self.clear_button.clicked.connect(self.clear_results)
        self.save_results_button.clicked.connect(self.save_results)

        button_layout.addWidget(self.search_button)
        button_layout.addWidget(self.stop_button)
        button_layout.addWidget(self.clear_button)
        button_layout.addWidget(self.save_results_button)
        layout.addLayout(button_layout)

    def _setup_extension_buttons(self, layout: QVBoxLayout) -> None:
        extensions_layout = QHBoxLayout()

        for button_label, extension in [
            ("List .xml Extensions", "xml"),
            ("List .dll Extensions", "dll"),
            ("List .png Extensions", "png"),
            ("List .dds Extensions", "dds"),
        ]:
            button = QPushButton(button_label)
            button.clicked.connect(
                lambda checked, ext=extension: self.list_extensions(str(ext))
            )
            extensions_layout.addWidget(button)

        layout.addLayout(extensions_layout)

    def selected_folder(self) -> str:
        folder = self.settings_controller.settings.instances[
            self.settings_controller.settings.current_instance
        ].local_folder
        if not folder:
            show_warning(
                title="Warning",
                text="Please set up locations in settings for search to function.",
            )
            return ""
        return str(folder)

    def start_search(self) -> None:
        # Show progress window and reset it
        self.progress_window.reset()
        self.progress_window.show()
        self.loading_bar.setVisible(True)

        self._generate_search_path()
        folder = self.get_default_search_path()

        self.clear_results()
        search_text = self.search_text.text() or ""

        search_options: Dict[str, bool | str] = {
            "folder": str(folder),
            "search_type": str(self.search_type_combo.currentText()),
            "case_sensitive": bool(self.case_sensitive_check.isChecked()),
            "include_git": bool(self.include_git_check.isChecked()),
            "include_languages": bool(self.include_languages_check.isChecked()),
            "include_source": bool(self.include_source_check.isChecked()),
        }

        logger.debug(f"Search options: {search_options}")

        search_path = self.get_default_search_path()
        self.search_thread = SearchThread(
            self.settings_controller, search_text, search_options, search_path, self
        )

        self.search_thread.search_result.connect(self.display_search_result)
        self.search_thread.search_progress.connect(self.progress_window.update_progress)
        self.search_thread.current_file.connect(
            self.progress_window.update_current_file
        )
        self.search_thread.file_count.connect(self.progress_window.update_file_count)

        self.search_thread.finished.connect(self.search_finished)

        self.search_thread.start()

    def display_search_result(self, result: str) -> None:
        try:
            if result.startswith("Total Results:") or result.startswith("Error:"):
                return

            path = Path(result)
            file_name = path.name
            file_path = str(path)

            # Get mod name from metadata using the file's parent directory
            mod_name = "Unknown Mod"
            try:
                # Find the mod UUID that matches this file path
                for (
                    uuid,
                    mod_data,
                ) in self.metadata_manager.internal_local_metadata.items():
                    mod_path = mod_data.get("path", "")
                    if mod_path and file_path.startswith(mod_path):
                        mod_name = mod_data.get(
                            "name", path.parent.name or "Unknown Mod"
                        )
                        break
            except Exception as e:
                logger.error(f"Error getting mod name: {e}")
                # Fallback to directory name if metadata lookup fails
                mod_name = path.parent.name if path.parent.name else "Unknown Mod"

            # Verify the search text matches either the file name or mod name
            search_text = self.search_text.text().lower()
            if (
                search_text not in file_name.lower()
                and search_text not in mod_name.lower()
            ):
                return

            # self.current_file_label.setText(f"Current File: {file_name}")

            row_position = self.search_results_table.rowCount()
            self.search_results_table.insertRow(row_position)
            self.search_results_table.setItem(
                row_position, 0, QTableWidgetItem(mod_name)
            )
            self.search_results_table.setItem(
                row_position, 1, QTableWidgetItem(file_name)
            )
            self.search_results_table.setItem(
                row_position, 2, QTableWidgetItem(file_path)
            )
        except Exception as e:
            logger.error(f"Error displaying search result: {e}")
            # self.current_file_label.setText("Current File: Error")

    def search_finished(self) -> None:
        """Handle search completion."""
        self.search_thread = None
        total_matches = self.search_results_table.rowCount()
        self.progress_window.update_file_count(total_matches)
        self.file_count_label.setText(f"Files Match Found: {total_matches}")
        self.loading_bar.setVisible(False)

    def stop_search(self) -> None:
        if self.search_thread:
            self.search_thread.requestInterruption()

    def save_results(self) -> None:
        if self.search_results_table.rowCount() == 0:
            show_warning(title="Warning", text="No results to save.")
            return
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Results", "", "Text Files (*.txt)"
        )
        if save_path:
            try:
                with open(save_path, "w") as f:
                    for row in range(self.search_results_table.rowCount()):
                        mod_name_item = self.search_results_table.item(row, 0)
                        file_name_item = self.search_results_table.item(row, 1)
                        file_path_item = self.search_results_table.item(row, 2)
                        mod_name = (
                            mod_name_item.text() if mod_name_item else "Unknown Mod"
                        )
                        file_name = (
                            file_name_item.text() if file_name_item else "Unknown File"
                        )
                        file_path = (
                            file_path_item.text() if file_path_item else "Unknown Path"
                        )

                        f.write(f"{mod_name}: {file_name}: {file_path}\n")
                logger.info(f"Results saved to {save_path}")
            except IOError as e:
                logger.error(f"Error saving results: {e}")
                show_warning(title="Error", text="Failed to save results.")

    def clear_results(self) -> None:
        self.search_results_table.setRowCount(0)

    def check_search_criteria(self, file: str, file_path: str) -> bool:
        """
        Check if a file matches the search criteria.

        Args:
            file (str): Name of the file
            file_path (str): Full path to the file

        Returns:
            bool: True if file matches criteria, False otherwise

        Raises:
            FileNotFoundError: If file cannot be found
            IOError: If file cannot be read
            OSError: For other file system related errors
        """

        if self.search_options["search_type"] == "File and Folder Names":
            logger.debug(f"Checking file: {file}")
            return self.search_text.text().lower() in file.lower()

        elif self.search_options["search_type"] == "Inside All Files":
            try:
                # Check file size before reading (limit to 10MB)
                file_size = os.path.getsize(file_path)
                if file_size > 10 * 1024 * 1024:  # 10MB
                    logger.warning(
                        f"Skipping large file: {file_path} ({file_size} bytes)"
                    )
                    return False

                # Use memory-mapped file for efficient large file reading
                import mmap

                search_bytes = self.search_text.text().lower().encode()

                with open(file_path, "r+b") as f:
                    # Memory-map the file
                    mmapped_file = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                    try:
                        # Convert mmap content to lowercase bytes for comparison
                        file_content = mmapped_file.read().lower()
                        if search_bytes in file_content:
                            return True
                        return False
                    finally:
                        mmapped_file.close()

            except (FileNotFoundError, IOError, OSError) as e:
                logger.error(f"Error reading {file_path}: {e}")
                logger.error(f"Error: Could not read file {file_path}")

                return False
        elif self.search_options["search_type"] == ".xml Extensions Only":
            return file.endswith(".xml")
        return False

    def list_extensions(self, extension: str) -> None:
        folder = self.get_default_search_path()
        if not folder:
            return

        self.clear_results()
        count = 0

        # Create search options for extension search
        self.search_options = {
            "folder": folder,
            "search_type": "File and Folder Names",
            "case_sensitive": False,
            "include_git": True,
            "include_languages": True,
            "include_source": True,
        }

        # Collect all files matching the extension
        for root, dirs, files in os.walk(folder):
            for file in files:
                if file.endswith("." + extension):
                    full_path = os.path.join(root, file)
                    path = Path(full_path)

                    # Use check_search_criteria to verify the file matches
                    if self.check_search_criteria(file, full_path):
                        # Get mod name using the same pattern as display_search_result
                        mod_name = "Unknown Mod"
                        try:
                            # First try to get mod name from active mods list
                            if hasattr(self.mods_panel.active_mods_list, "uuids"):
                                for uuid in self.mods_panel.active_mods_list.uuids:
                                    mod_data = self.metadata_manager.internal_local_metadata.get(
                                        uuid
                                    )
                                    if mod_data:
                                        mod_path = mod_data.get("path", "")
                                        if mod_path and full_path.startswith(mod_path):
                                            mod_name = mod_data.get(
                                                "name",
                                                path.parent.name or "Unknown Mod",
                                            )
                                            break
                            # Fallback to searching all metadata if not found in active mods
                            if mod_name == "Unknown Mod":
                                for (
                                    uuid,
                                    mod_data,
                                ) in self.metadata_manager.internal_local_metadata.items():
                                    mod_path = mod_data.get("path", "")
                                    if mod_path and full_path.startswith(mod_path):
                                        mod_name = mod_data.get(
                                            "name", path.parent.name or "Unknown Mod"
                                        )
                                        break
                        except Exception as e:
                            logger.error(f"Error getting mod name: {e}")
                            # Fallback to directory name if metadata lookup fails
                            mod_name = (
                                path.parent.name if path.parent.name else "Unknown Mod"
                            )

                        # Add to results table
                        self.search_results_table.insertRow(
                            self.search_results_table.rowCount()
                        )
                        self.search_results_table.setItem(
                            self.search_results_table.rowCount() - 1,
                            0,
                            QTableWidgetItem(mod_name),
                        )
                        self.search_results_table.setItem(
                            self.search_results_table.rowCount() - 1,
                            1,
                            QTableWidgetItem(file),
                        )
                        self.search_results_table.setItem(
                            self.search_results_table.rowCount() - 1,
                            2,
                            QTableWidgetItem(full_path),
                        )
                        count += 1

        if count == 0:
            self.search_results_table.insertRow(self.search_results_table.rowCount())
            self.search_results_table.setItem(
                self.search_results_table.rowCount() - 1,
                0,
                QTableWidgetItem(f"No files found with the .{extension} extension."),
            )

        else:
            self.search_results_table.insertRow(self.search_results_table.rowCount())
            self.search_results_table.setItem(
                self.search_results_table.rowCount() - 1,
                0,
                QTableWidgetItem(f"No files found with the .{extension} extension."),
            )

    def _generate_search_path(self) -> None:
        """
        Generate search paths based on selected mod scope.

        This method creates a temporary file containing the paths to search based on the selected mod settings.
        """

        if os.path.exists(self.search_txt_path):
            os.remove(self.search_txt_path)
        if self.mod_select_combo.currentText() == "All Mods":
            local_mods_target = self.settings_controller.settings.instances[
                self.settings_controller.settings.current_instance
            ].local_folder
            if local_mods_target and local_mods_target != "":
                with open(
                    self.search_txt_path, "a", encoding="utf-8"
                ) as search_txt_file:
                    search_txt_file.write(os.path.abspath(local_mods_target) + "\n")
            workshop_mods_target = self.settings_controller.settings.instances[
                self.settings_controller.settings.current_instance
            ].workshop_folder
            if workshop_mods_target and workshop_mods_target != "":
                with open(
                    self.search_txt_path, "a", encoding="utf-8"
                ) as search_txt_file:
                    search_txt_file.write(os.path.abspath(workshop_mods_target) + "\n")
        else:
            with open(self.search_txt_path, "a", encoding="utf-8") as search_txt_file:
                if hasattr(self.mods_panel.active_mods_list, "uuids"):
                    for uuid in self.mods_panel.active_mods_list.uuids:
                        mod_data = self.metadata_manager.internal_local_metadata.get(
                            uuid
                        )
                        if mod_data and "path" in mod_data:
                            mod_path = mod_data["path"]
                            if mod_path and os.path.exists(mod_path):
                                search_txt_file.write(os.path.abspath(mod_path) + "\n")
                            else:
                                logger.warning(
                                    f"Mod path does not exist or is invalid: {mod_path}"
                                )
                        else:
                            logger.warning(f"Could not find mod data for UUID: {uuid}")
                else:
                    logger.error("Active mods list does not have 'uuids' attribute")

    def get_default_search_path(self) -> str:
        """Retrieve the default search path based on selected mod scope."""
        try:
            with open(self.search_txt_path, "r") as file:
                return file.read().strip()
        except FileNotFoundError:
            logger.error(
                f"search_path.txt not found in temp directory: {self.search_txt_path}"
            )
            return ""


def test_progress_window() -> None:
    """Main test function for ProgressWindow.

    Creates and shows a ProgressWindow, then simulates a search operation
    with progress updates. The window remains open after completion.
    """

    app = QApplication(sys.argv)

    # Create and show the progress window
    window = ProgressWindow()
    window.show()

    # Simulate search progress
    try:
        for i in range(101):
            window.update_progress(i)
            window.update_current_file(f"/path/to/file_{i}.txt")
            window.update_file_count(i)
            time.sleep(0.1)  # Increased delay for better visibility
            app.processEvents()

            # Exit early if window is closed
            if not window.isVisible():
                break

        # Keep window open after completion
        if window.isVisible():
            window.cancel_button.setText("Done")
            window.cancel_button.clicked.connect(window.close)

    except Exception as e:
        print(f"Error during test: {e}")

    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        test_progress_window()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
