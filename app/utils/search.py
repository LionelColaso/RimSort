import os
import sys
from typing import Dict, List, Optional, Union

from loguru import logger
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.controllers.settings_controller import SettingsController
from app.views.dialogue import show_warning


class SearchThread(QThread):
    """
    A thread for performing file and folder searches in the background.

    Emits:
        search_result (Signal): Emits search results as strings.
        search_progress (Signal): Emits progress as integers (0-100).
    """

    search_result = Signal(str)
    search_progress = Signal(int)

    def __init__(
        self, search_text: str, search_options: Dict[str, Union[bool, str]]
    ) -> None:
        super().__init__()
        assert isinstance(search_text, str), "search_text must be a string"
        for key, value in search_options.items():
            assert isinstance(
                value, (bool, str)
            ), f"Invalid type for {key}: {type(value)}"
        self.search_text = (
            search_text.lower()
            if not search_options.get("case_sensitive")
            else search_text
        )
        self.search_options = search_options

    def run(self) -> None:
        """
        Execute the search process, iterating through files and folders.
        """
        folder = str(self.search_options["folder"])
        exclude_folders = self._get_exclude_folders()

        # Calculate total files for progress tracking
        total_files = sum(len(files) for _, _, files in os.walk(folder))
        if total_files == 0:
            logger.warning("No files found in the specified folder.")
            self.search_result.emit("No files found.")
            return

        count, processed_files = 0, 0
        for root, dirs, files in os.walk(folder):
            if self.isInterruptionRequested():
                return

            # Exclude specified folders
            dirs[:] = [d for d in dirs if d not in exclude_folders]
            for file in files:
                file_path = os.path.join(root, file)
                if self._matches_search_criteria(file, file_path):
                    count += 1
                    logger.debug(f"Processing file: {file_path}")
                    self.search_result.emit(file_path)
                processed_files += 1
                self.search_progress.emit(int((processed_files / total_files) * 100))

        self.search_result.emit(f"Total Results: {count}")

    def _get_exclude_folders(self) -> List[str]:
        """
        Determine which folders to exclude from the search.

        Returns:
            List[str]: A list of folder names to exclude.
        """
        exclude_folders: List[str] = []
        if not self.search_options.get("include_git"):
            exclude_folders.append(".git")
        if not self.search_options.get("include_languages"):
            exclude_folders.extend(["Languages", "languages"])
        if not self.search_options.get("include_source"):
            exclude_folders.extend(["Source", "source"])
        return exclude_folders

    def _matches_search_criteria(self, file: str, file_path: str) -> bool:
        """
        Check if a file matches the search criteria.

        Args:
            file (str): The name of the file.
            file_path (str): The full path of the file.

        Returns:
            bool: True if the file matches the criteria, False otherwise.
        """
        if self.search_options["search_type"] == "File and Folder Names":
            return self.search_text in file.lower()
        elif self.search_options["search_type"] == "Inside All Files":
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    return self.search_text in f.read().lower()
            except (FileNotFoundError, IOError) as e:
                logger.error(f"Error reading {file_path}: {e}")
                return False
        elif self.search_options["search_type"] == ".xml Extensions Only":
            return file.endswith(".xml")
        return False


class SearchTool(QMainWindow):
    """
    Main application window for the file search tool.
    """

    def __init__(
        self,
        settings_controller: SettingsController,
    ) -> None:
        super().__init__()
        self.settings_controller = settings_controller
        self.search_thread: Optional[SearchThread] = None
        self.setWindowTitle("File Search")
        self.setMinimumSize(800, 600)

        main_widget = QWidget()
        layout = QVBoxLayout(main_widget)

        # Setup UI components
        self._setup_folder_selection(layout)
        self._setup_search_input(layout)
        self._setup_search_options(layout)
        self._setup_progress_bar(layout)
        self._setup_search_buttons(layout)
        self._setup_search_results(layout)
        self._setup_extension_buttons(layout)
        self._setup_save_clear_buttons(layout)

        self.setCentralWidget(main_widget)

    def _setup_folder_selection(self, layout: QVBoxLayout) -> None:
        """
        Set up the folder selection UI.
        """
        folder_layout = QHBoxLayout()
        self.folder_label = QLabel("Selected Folder: ")
        self.folder_path_label = QLabel()
        folder_layout.addWidget(self.folder_label)
        folder_layout.addWidget(self.folder_path_label)
        layout.addLayout(folder_layout)

    def _setup_search_input(self, layout: QVBoxLayout) -> None:
        """
        Set up the search input field.
        """
        self.search_text = QLineEdit()
        self.search_text.setPlaceholderText("Enter search text")
        self.search_text.returnPressed.connect(self.start_search)
        layout.addWidget(self.search_text)

    def _setup_search_options(self, layout: QVBoxLayout) -> None:
        """
        Set up search filter options.
        """
        options_layout = QVBoxLayout()
        options_layout.addWidget(QLabel("Search Filter:"))
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

        options_layout.addWidget(QLabel("Search Type:"))
        self.search_type_combo = QComboBox()
        self.search_type_combo.addItems(
            ["File and Folder Names", "Inside All Files", ".xml Extensions Only"]
        )
        self.search_type_combo.setCurrentIndex(2)
        options_layout.addWidget(self.search_type_combo)
        layout.addLayout(options_layout)

    def _setup_progress_bar(self, layout: QVBoxLayout) -> None:
        """
        Set up the progress bar.
        """
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

    def _setup_search_buttons(self, layout: QVBoxLayout) -> None:
        """
        Set up the search and stop buttons.
        """
        search_buttons_layout = QHBoxLayout()
        self.search_button = QPushButton("Search")
        self.stop_button = QPushButton("Stop")
        self.search_button.clicked.connect(self.start_search)
        self.stop_button.clicked.connect(self.stop_search)

        for button in [self.search_button, self.stop_button]:
            search_buttons_layout.addWidget(button)
        layout.addLayout(search_buttons_layout)

    def _setup_search_results(self, layout: QVBoxLayout) -> None:
        """
        Set up the search results display.
        """
        self.search_results_text = QTextEdit()
        self.search_results_text.setReadOnly(True)
        layout.addWidget(self.search_results_text)

    def _setup_extension_buttons(self, layout: QVBoxLayout) -> None:
        """
        Set up buttons for listing files by extension.
        """
        extensions_layout = QHBoxLayout()
        for button_label, extension in [
            ("List .xml Extensions", "xml"),
            ("List .dll Extensions", "dll"),
            ("List .png Extensions", "png"),
            ("List .dds Extensions", "dds"),
        ]:
            button = QPushButton(button_label)
            button.clicked.connect(lambda ext=extension: self.list_extensions(ext))
            extensions_layout.addWidget(button)
        layout.addLayout(extensions_layout)

    def _setup_save_clear_buttons(self, layout: QVBoxLayout) -> None:
        """
        Set up buttons for saving and clearing results.
        """
        button_layout = QHBoxLayout()
        self.save_results_button = QPushButton("Save Results to .txt")
        self.clear_button = QPushButton("Clear")
        self.save_results_button.clicked.connect(self.save_results)
        self.clear_button.clicked.connect(self.clear_results)

        for button in [self.save_results_button, self.clear_button]:
            button_layout.addWidget(button)
        layout.addLayout(button_layout)

    def selected_folder(self) -> str:
        """
        Retrieve the selected folder from settings.

        Returns:
            str: The path to the selected folder or None if not set.
        """
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
        """
        Initiate the search process.
        """
        folder = self.selected_folder()
        if not folder or not os.path.exists(folder):
            show_warning("Warning", "Please set up a valid folder in settings.")
            return

        self.clear_results()
        search_text = self.search_text.text() or ""  # Ensure search_text is a string
        search_options = {
            "folder": str(folder),  # Ensure folder is a string
            "search_type": str(
                self.search_type_combo.currentText()
            ),  # Explicit cast to str
            "case_sensitive": bool(
                self.case_sensitive_check.isChecked()
            ),  # Explicit cast to bool
            "include_git": bool(self.include_git_check.isChecked()),
            "include_languages": bool(self.include_languages_check.isChecked()),
            "include_source": bool(self.include_source_check.isChecked()),
        }
        logger.debug(f"Search options: {search_options}")

        self.progress_bar.setValue(0)
        self.search_thread = SearchThread(search_text, search_options)
        self.search_thread.search_result.connect(self.display_search_result)
        self.search_thread.search_progress.connect(self.update_progress)
        self.search_thread.finished.connect(self.search_finished)
        self.search_thread.start()

    def display_search_result(self, result: str) -> None:
        """
        Display a search result in the results text area.

        Args:
            result (str): The search result to display.
        """
        self.search_results_text.append(result)

    def search_finished(self) -> None:
        """
        Handle the completion of the search process.
        """
        self.search_thread = None
        self.progress_bar.setValue(0)

    def stop_search(self) -> None:
        """
        Stop the ongoing search process.
        """
        if self.search_thread:
            self.search_thread.requestInterruption()

    def save_results(self) -> None:
        """
        Save the search results to a text file.
        """
        if not self.search_results_text.toPlainText():
            show_warning(title="Warning", text="No results to save.")
            return
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Results", "", "Text Files (*.txt)"
        )
        if save_path:
            try:
                with open(save_path, "w") as f:
                    f.write(self.search_results_text.toPlainText())
                logger.info(f"Results saved to {save_path}")
            except IOError as e:
                logger.error(f"Error saving results: {e}")
                show_warning(title="Error", text="Failed to save results.")

    def clear_results(self) -> None:
        """
        Clear the search results text area.
        """
        self.search_results_text.clear()

    def list_extensions(self, extension: str) -> None:
        """
        List files with the specified extension in the selected folder.

        Args:
            extension (str): The file extension to filter by.
        """
        folder = self.selected_folder()
        if not folder:
            return
        if not os.path.exists(folder):
            show_warning(title="Error", text=f"Folder {folder} does not exist.")
            return

        extensions = [
            file
            for root, dirs, files in os.walk(folder)
            for file in files
            if file.endswith("." + extension)
        ]
        self.clear_results()

        if extensions:
            self.search_results_text.append(
                f"List of .{extension} Extensions:\n" + "\n".join(extensions)
            )
        else:
            self.search_results_text.append(
                f"No files found with the .{extension} extension."
            )

    def update_progress(self, progress: int) -> None:
        """
        Update the progress bar.

        Args:
            progress (int): Progress percentage (0-100).
        """
        self.progress_bar.setValue(progress)


if __name__ == "__main__":
    sys.exit()
