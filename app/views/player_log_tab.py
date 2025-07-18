import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger
from PySide6.QtCore import QObject, QPoint, QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from app.controllers.settings_controller import SettingsController
from app.views.dialogue import show_information, show_warning


class LogHighlighter(QSyntaxHighlighter):
    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)

        # Define color formats
        self.error_format = self._make_format("#FF0000", bold=True)
        self.warning_format = self._make_format("#FF8C00", bold=True)
        self.exception_format = QTextCharFormat()
        self.exception_format.setForeground(QColor("#DC143C"))
        self.exception_format.setBackground(QColor("#FFFFFF"))
        self.info_format = self._make_format("#00FF0D", bold=True)
        self.mod_format = self._make_format("#1100FFFF", bold=True)
        self.timestamp_format = self._make_format("#00EEFF")
        self.keybind_format = self._make_format("#EEFF00", bold=True)

        self.search_format = QTextCharFormat()
        self.search_format.setBackground(QColor("#0076FC"))

        self.search_term: Optional[str] = None
        self._search_regex: Optional[re.Pattern[str]] = None  # Cache compiled regex

        # Define patterns with priority (higher index = higher priority)
        self.patterns = [
            (re.compile(r"key binding conflict", re.IGNORECASE), self.keybind_format),
            (re.compile(r"\d{1,2}:\d{2}:\d{2} [AP]M"), self.timestamp_format),
            (re.compile(r"\[([^\]]+)\]"), self.mod_format),
            (
                re.compile(
                    r"(?i)\b(info|initialized|loaded|start(ed)?|done|success)\b"
                ),
                self.info_format,
            ),
            (re.compile(r"(?i)\b(warning|warn|deprecat)\b"), self.warning_format),
            (re.compile(r"\[W\]"), self.warning_format),
            (
                re.compile(r"(?i)\b(error|failed|exception|fatal|critical)\b"),
                self.error_format,
            ),
            (re.compile(r"\[E\]"), self.error_format),
            (re.compile(r".*Exception.*:|.*Error.*:"), self.exception_format),
            (re.compile(r"^\s*at .*"), self.exception_format),
        ]

    def set_highlight_color(self, color: QColor) -> None:
        """Set the color used for search term highlighting and quick navigation."""
        self.search_format.setBackground(color)
        self.rehighlight()

    def set_search_term(self, term: Optional[str]) -> None:
        """Set the current search term and compile regex for highlighting."""
        self.search_term = term
        if term:
            try:
                self._search_regex = re.compile(re.escape(term), re.IGNORECASE)
            except re.error:
                self._search_regex = None
        else:
            self._search_regex = None
        self.rehighlight()

    def _make_format(self, color: str, bold: bool = False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        return fmt

    def highlightBlock(self, text: str) -> None:
        # Highlight search matches first (highest priority)
        if self._search_regex:
            try:
                for match in self._search_regex.finditer(text):
                    start, end = match.span()
                    self.setFormat(start, end - start, self.search_format)
            except Exception:
                pass
        # Apply other patterns
        for pattern, fmt in self.patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                self.setFormat(start, end - start, fmt)


class PlayerLogTab(QWidget):
    matches: list[QTextCursor]
    last_log_size: int
    total_lines_label: QLabel
    errors_label: QLabel
    warnings_label: QLabel
    exceptions_label: QLabel
    mod_issues_label: QLabel
    keybind_label: QLabel
    info_label: QLabel
    match_count_label: QLabel

    # Precompile regex patterns for filtering and analysis
    _error_pattern = re.compile(r"[e]|error|failed|fatal", re.IGNORECASE)
    _warning_pattern = re.compile(r"[w]|warning|warn|deprecat", re.IGNORECASE)
    _exception_pattern = re.compile(r"exception", re.IGNORECASE)
    _mod_issue_pattern = re.compile(
        r"(\[.*\].*(error|warning|exception))|(mod.*(conflict|issue))", re.IGNORECASE
    )
    _keybind_pattern = re.compile(r"key binding conflict", re.IGNORECASE)
    _info_pattern = re.compile(
        r"\b(info|initialized|loaded|start(ed)?|done|success)\b", re.IGNORECASE
    )

    def __init__(self, settings_controller: SettingsController) -> None:
        super().__init__()
        self.settings_controller = settings_controller
        self.player_log_path: Optional[Path] = None
        self.current_log_content: str = ""
        self.filtered_content: str = ""
        self.log_stats: dict[str, int] = {
            "errors": 0,
            "warnings": 0,
            "exceptions": 0,
            "total_lines": 0,
            "mod_issues": 0,
            "keybind_conflicts": 0,
            "info": 0,
        }
        self.highlighter: LogHighlighter
        self.log_display: QTextEdit
        self.current_match_index: int = -1
        self.matches = []
        self.filter_combo: Optional[QComboBox] = None
        self.mod_filter_input: Optional[QLineEdit] = None
        self.last_log_size: int = 0

        self.quick_nav_highlight_format = QTextCharFormat()
        self.quick_nav_highlight_format.setBackground(QColor("#0076FC"))

        self.init_ui()
        self.auto_load_player_log_on_startup_checkbox.setChecked(
            self.settings_controller.settings.auto_load_player_log_on_startup
        )
        self.auto_load_player_log_on_startup_checkbox.toggled.connect(
            self._on_auto_load_player_log_on_startup_toggled
        )
        self.player_log_path = self._get_player_log_path()
        # Set checkbox state from settings
        if self.settings_controller.settings.auto_load_player_log_on_startup:
            self.load_log()

    def _on_auto_load_player_log_on_startup_toggled(self, checked: bool) -> None:
        self.settings_controller.settings.auto_load_player_log_on_startup = checked
        self.settings_controller.settings.save()

    def set_highlight_color(self, color: QColor) -> None:
        self.highlighter.set_highlight_color(color)
        self.quick_nav_highlight_format.setBackground(color)
        self._highlight_quick_navigation(color)

    def _highlight_quick_navigation(self, color: QColor) -> None:
        """Highlight quick navigation matches with the given color."""
        self.highlighter.set_highlight_color(color)
        self.search_text_changed(self.search_input.text() if self.search_input else "")

    def clear_log_display(self) -> None:
        self.log_display.clear()

    def scroll_to_end(self) -> None:
        cursor = self.log_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_display.setTextCursor(cursor)
        self.log_display.ensureCursorVisible()

    def _get_player_log_path(self) -> Optional[Path]:
        try:
            current_instance: str = self.settings_controller.settings.current_instance
            config_folder: str = self.settings_controller.settings.instances[
                current_instance
            ].config_folder
            player_log_path: Path = Path(config_folder).parent / "Player.log"
            if player_log_path.exists():
                return player_log_path
        except Exception:
            pass
        return None

    def pick_highlight_color(self) -> None:
        color = QColorDialog.getColor(
            self.highlighter.search_format.background().color(),
            self,
            "Pick Highlight Color",
        )
        if color.isValid():
            self.set_highlight_color(color)

    def init_ui(self) -> None:
        self.main_layout = QVBoxLayout()

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self.left_panel = QWidget()
        self.left_panel.setMaximumWidth(450)
        self.left_panel.setMinimumWidth(250)
        self.left_panel.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        self.left_layout = QVBoxLayout(self.left_panel)

        self.right_panel = QWidget()
        self.right_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.right_layout = QVBoxLayout(self.right_panel)

        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFont(QFont("Consolas", 10))
        self.log_display.setMinimumSize(400, 200)
        self.log_display.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.log_display.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.log_display.customContextMenuRequested.connect(self.show_context_menu)
        self.right_layout.addWidget(self.log_display)

        self.highlighter = LogHighlighter(self.log_display.document())

        self.splitter.addWidget(self.left_panel)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setSizes([450, 1000])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        self.main_layout.addWidget(self.splitter)
        self.setLayout(self.main_layout)

        self.tabs = QTabWidget()
        self.left_layout.addWidget(self.tabs)

        # File info group
        file_info_group = QGroupBox("File Info")
        file_info_layout = QVBoxLayout()
        file_info_group.setLayout(file_info_layout)

        self.file_path_label = QLabel("Path:")
        self.file_path_label.setWordWrap(True)
        file_info_layout.addWidget(self.file_path_label)

        self.file_size_label = QLabel("Size:")
        file_info_layout.addWidget(self.file_size_label)

        self.last_modified_label = QLabel("Modified:")
        file_info_layout.addWidget(self.last_modified_label)

        self.growth_label = QLabel("")
        self.growth_label.setStyleSheet("color: green; font-weight: bold;")
        file_info_layout.addWidget(self.growth_label)

        file_info_layout.addStretch()
        self.tabs.addTab(file_info_group, "File Info")

        # Statistics group
        stats_group = QGroupBox("Statistics")
        stats_layout = QVBoxLayout()
        stats_group.setLayout(stats_layout)

        self.total_lines_label = QLabel("Total Lines: 0")
        self.info_label = QLabel("Info: 0")
        self.mod_issues_label = QLabel("Mod Issues: 0")
        self.warnings_label = QLabel("Warnings: 0")
        self.errors_label = QLabel("Errors: 0")
        self.exceptions_label = QLabel("Exceptions: 0")
        self.keybind_label = QLabel("Keybind Conflicts: 0")

        stats_layout.addWidget(self.total_lines_label)
        stats_layout.addWidget(self.info_label)
        stats_layout.addWidget(self.mod_issues_label)
        stats_layout.addWidget(self.warnings_label)
        stats_layout.addWidget(self.errors_label)
        stats_layout.addWidget(self.exceptions_label)
        stats_layout.addWidget(self.keybind_label)

        self.left_layout.addWidget(stats_group)

        self.left_layout.addStretch()

        # Controls group
        controls_group = QGroupBox("Controls")
        controls_layout = QVBoxLayout()
        controls_group.setLayout(controls_layout)

        self.auto_load_player_log_on_startup_checkbox = QCheckBox(
            "Auto Load Game Log on Startup"
        )
        self.auto_load_player_log_on_startup_checkbox.setToolTip(
            "If checked, the Game log will be loaded automatically on startup."
        )
        controls_layout.addWidget(self.auto_load_player_log_on_startup_checkbox)

        self.real_time_monitor_checkbox = QCheckBox("Enable Real-Time Log Monitoring")
        self.real_time_monitor_checkbox.setToolTip(
            "Enable real-time monitoring of Player.log file changes."
        )
        self.real_time_monitor_checkbox.toggled.connect(
            self.toggle_real_time_monitoring
        )
        controls_layout.addWidget(self.real_time_monitor_checkbox)

        load_buttons_layout = QHBoxLayout()
        self.load_default_button = QPushButton("Load Game Log")
        self.load_default_button.setToolTip("Loads the game's Player.log file.")
        self.load_default_button.clicked.connect(self.load_default_log)
        load_buttons_layout.addWidget(self.load_default_button)

        self.load_file_button = QPushButton("Load Log from File")
        self.load_file_button.setToolTip("Open a file dialog to select a log file")
        self.load_file_button.clicked.connect(self.load_log_from_file)
        load_buttons_layout.addWidget(self.load_file_button)

        self.load_link_button = QPushButton("Load Log from Link")
        self.load_link_button.setToolTip("Load log content from a URL")
        self.load_link_button.clicked.connect(self.load_log_from_link)
        load_buttons_layout.addWidget(self.load_link_button)

        controls_layout.addLayout(load_buttons_layout)

        button_layout = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_log)
        self.export_button = QPushButton("Export")
        self.export_button.clicked.connect(self.export_log)
        self.clear_button = QPushButton("Clear Log Display")
        self.clear_button.clicked.connect(self.clear_log_display)
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(self.export_button)
        button_layout.addWidget(self.clear_button)
        controls_layout.addLayout(button_layout)

        self.left_layout.addWidget(controls_group)

        # Search group
        search_group = QGroupBox("Search")
        search_layout = QVBoxLayout()
        search_group.setLayout(search_layout)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search log entries...")
        self._search_debounce_timer = QTimer(self)
        self._search_debounce_timer.setSingleShot(True)
        self._search_debounce_timer.setInterval(300)  # 300ms debounce
        self.search_input.textChanged.connect(self._on_search_text_changed_debounced)
        self._search_debounce_timer.timeout.connect(self._do_search_text_changed)

        search_layout.addWidget(self.search_input)

        search_nav_layout = QHBoxLayout()
        self.color_picker_button = QPushButton("Highlight Color")
        self.color_picker_button.setToolTip(
            "Pick color for search and navigation highlighting"
        )
        self.prev_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        match_count_label = QLabel("0/0")

        self.color_picker_button.clicked.connect(self.pick_highlight_color)
        self.prev_button.clicked.connect(self.goto_previous_match)
        self.next_button.clicked.connect(self.goto_next_match)

        search_nav_layout.addWidget(self.color_picker_button)
        search_nav_layout.addWidget(self.prev_button)
        search_nav_layout.addWidget(self.next_button)
        search_nav_layout.addWidget(match_count_label)
        search_layout.addLayout(search_nav_layout)

        self.match_count_label = match_count_label

        self.match_count_label.setObjectName("match_count_label")

        self.left_layout.addWidget(search_group)

        # Filter group
        filter_group = QGroupBox("Filter")
        filter_layout = QHBoxLayout()
        filter_group.setLayout(filter_layout)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(
            [
                "All Entries",
                "Errors Only",
                "Warnings & Errors",
                "Exceptions Only",
                "Mod Issues",
                "Keybind Conflicts",
                "No Issues",
            ]
        )
        self.filter_combo.currentIndexChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.filter_combo)

        self.mod_filter_input = QLineEdit()
        self.mod_filter_input.setPlaceholderText("Filter by mod name...")
        self.mod_filter_input.textChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.mod_filter_input)

        self.left_layout.addWidget(filter_group)

        # Quick navigation group
        nav_group = QGroupBox("Quick Navigation")
        nav_layout = QGridLayout()
        nav_group.setLayout(nav_layout)

        self.goto_error_prev_btn = QPushButton("Previous Error")
        self.goto_error_prev_btn.setToolTip("Jump to previous error entry")
        self.goto_error_prev_btn.clicked.connect(
            lambda: self.goto_previous_pattern(
                r"(?i)(error|failed|fatal|critical|\[E\])"
            )
        )
        self.goto_error_next_btn = QPushButton("Next Error")
        self.goto_error_next_btn.setToolTip("Jump to next error entry")
        self.goto_error_next_btn.clicked.connect(
            lambda: self.goto_first_pattern(r"(?i)(error|failed|fatal|critical|\[E\])")
        )
        self.goto_warning_prev_btn = QPushButton("Previous Warning")
        self.goto_warning_prev_btn.setToolTip("Jump to previous warning entry")
        self.goto_warning_prev_btn.clicked.connect(
            lambda: self.goto_previous_pattern(r"(?i)(warning|warn|deprecat|\[W\])")
        )
        self.goto_warning_next_btn = QPushButton("Next Warning")
        self.goto_warning_next_btn.setToolTip("Jump to next warning entry")
        self.goto_warning_next_btn.clicked.connect(
            lambda: self.goto_first_pattern(r"(?i)(warning|warn|deprecat|\[W\])")
        )
        self.goto_exception_prev_btn = QPushButton("Previous Exception")
        self.goto_exception_prev_btn.setToolTip("Jump to previous exception entry")
        self.goto_exception_prev_btn.clicked.connect(
            lambda: self.goto_previous_pattern(r"Exception|Error:")
        )
        self.goto_exception_next_btn = QPushButton("Next Exception")
        self.goto_exception_next_btn.setToolTip("Jump to next exception entry")
        self.goto_exception_next_btn.clicked.connect(
            lambda: self.goto_first_pattern(r"Exception|Error:")
        )
        self.goto_mod_prev_btn = QPushButton("Previous Mod Issue")
        self.goto_mod_prev_btn.setToolTip("Jump to previous mod issue entry")
        self.goto_mod_prev_btn.clicked.connect(
            lambda: self.goto_previous_pattern(r"\[.*\]")
        )
        self.goto_mod_next_btn = QPushButton("Next Mod Issue")
        self.goto_mod_next_btn.setToolTip("Jump to next mod issue entry")
        self.goto_mod_next_btn.clicked.connect(
            lambda: self.goto_first_pattern(r"\[.*\]")
        )
        self.goto_keybind_prev_btn = QPushButton("Previous Keybind Conflict")
        self.goto_keybind_prev_btn.setToolTip("Jump to previous keybind conflict entry")
        self.goto_keybind_prev_btn.clicked.connect(
            lambda: self.goto_previous_pattern(r"key binding conflict")
        )
        self.goto_keybind_next_btn = QPushButton("Next Keybind Conflict")
        self.goto_keybind_next_btn.setToolTip("Jump to next keybind conflict entry")
        self.goto_keybind_next_btn.clicked.connect(
            lambda: self.goto_first_pattern(r"key binding conflict")
        )
        self.goto_info_prev_btn = QPushButton("Previous Info")
        self.goto_info_prev_btn.setToolTip("Jump to previous info entry")
        self.goto_info_prev_btn.clicked.connect(
            lambda: self.goto_previous_pattern(
                r"(?i)(info|initialized|loaded|start(ed)?|done|success)"
            )
        )
        self.goto_info_next_btn = QPushButton("Next Info")
        self.goto_info_next_btn.setToolTip("Jump to next info entry")
        self.goto_info_next_btn.clicked.connect(
            lambda: self.goto_first_pattern(
                r"(?i)(info|initialized|loaded|start(ed)?|done|success)"
            )
        )
        self.scroll_to_end_btn = QPushButton("Scroll to End")
        self.scroll_to_end_btn.setToolTip("Scroll to the end of the log display")
        self.scroll_to_end_btn.clicked.connect(self.scroll_to_end)

        nav_layout.addWidget(self.scroll_to_end_btn, 5, 0, 1, 2)
        nav_layout.addWidget(self.goto_error_prev_btn, 0, 0)
        nav_layout.addWidget(self.goto_error_next_btn, 0, 1)
        nav_layout.addWidget(self.goto_warning_prev_btn, 1, 0)
        nav_layout.addWidget(self.goto_warning_next_btn, 1, 1)
        nav_layout.addWidget(self.goto_exception_prev_btn, 2, 0)
        nav_layout.addWidget(self.goto_exception_next_btn, 2, 1)
        nav_layout.addWidget(self.goto_mod_prev_btn, 3, 0)
        nav_layout.addWidget(self.goto_mod_next_btn, 3, 1)
        nav_layout.addWidget(self.goto_keybind_prev_btn, 4, 0)
        nav_layout.addWidget(self.goto_keybind_next_btn, 4, 1)
        nav_layout.addWidget(self.goto_info_prev_btn, 5, 0)
        nav_layout.addWidget(self.goto_info_next_btn, 5, 1)

        self.left_layout.addWidget(nav_group)

        # Load the log initially
        self.load_log()

    def on_file_changed(self) -> None:
        """Handle file changed signal to read appended content or reload if truncated."""
        try:
            if self.player_log_path is None:
                return
            current_size = self.player_log_path.stat().st_size
            logger.debug(
                f"on_file_changed: current_size={current_size}, last_log_size={self.last_log_size}"
            )
            with open(
                self.player_log_path, "r", encoding="utf-8", errors="ignore"
            ) as f:
                content = f.read()
                logger.debug("File changed signal received, processing log update.")
                if current_size < self.last_log_size:
                    logger.debug(
                        "File size smaller than last log size, treating as reset."
                    )
                    self.current_log_content = content
                    self.last_log_size = current_size
                    if (
                        self.filter_combo
                        and self.filter_combo.currentText() != "All Entries"
                    ):
                        self.filter_combo.setCurrentText("All Entries")
                    self.filtered_content = ""
                    self.log_display.clear()
                else:
                    lines = content.splitlines()
                    reset_index = -1
                    for i in range(len(lines) - 1, -1, -1):
                        if lines[i].startswith("Mono path"):
                            reset_index = i
                            break
                    if reset_index != -1 and not self.current_log_content.startswith(
                        "Mono path"
                    ):
                        logger.debug(
                            f"Log reset signature detected at line {reset_index}. Resetting log content."
                        )
                        self.current_log_content = "\n".join(lines[reset_index:])
                        self.last_log_size = len(self.current_log_content)
                        if (
                            self.filter_combo
                            and self.filter_combo.currentText() != "All Entries"
                        ):
                            self.filter_combo.setCurrentText("All Entries")
                        self.filtered_content = ""
                        self.log_display.clear()
                    new_content = ""
                    if current_size > self.last_log_size:
                        new_content = content[self.last_log_size :]
                        # Fix string formatting warning by using !r to get repr of bytes
                        logger.debug(
                            f"Appending {len(new_content)} bytes of new log content: {new_content!r}"
                        )
                        if isinstance(new_content, bytes):
                            new_content = new_content.decode("utf-8", errors="ignore")
                    if new_content.startswith("Mono path"):
                        self.current_log_content = new_content
                    else:
                        self.current_log_content += new_content
                    self.last_log_size = current_size
            self._analyze_log_content(self.current_log_content)
            self._update_statistics()
            self.apply_filter()
            self.scroll_to_end()
        except Exception as e:
            # Fix string formatting warning by decoding bytes if needed and avoid incompatible assignment
            error_message: str
            if isinstance(e, bytes):
                error_message = e.decode("utf-8", errors="ignore")
            else:
                error_message = str(e)
            logger.error(f"Error reading appended log content: {error_message}")

    def _on_search_text_changed_debounced(self, text: str) -> None:
        self._pending_search_text = text
        self._search_debounce_timer.start()

    def _do_search_text_changed(self) -> None:
        text = getattr(self, "_pending_search_text", "")
        self.search_text_changed(text)

    def show_context_menu(self, pos: QPoint) -> None:
        menu = self.log_display.createStandardContextMenu()
        cursor = self.log_display.textCursor()
        if cursor.hasSelection():
            menu.addSeparator()
            copy_action = menu.addAction("Copy Selection")
            copy_action.triggered.connect(self.log_display.copy)
        menu.exec(self.log_display.mapToGlobal(pos))

    def goto_first_pattern(self, pattern: str) -> None:
        document = self.log_display.document()
        regex = QRegularExpression(pattern)
        cursor = document.find(regex)

        if not cursor.isNull():
            self._apply_quick_nav_highlight(cursor)
            self.log_display.setTextCursor(cursor)
            self.log_display.ensureCursorVisible()
        else:
            show_information("Pattern not found in the current view.")

    def goto_previous_pattern(self, pattern: str) -> None:
        document = self.log_display.document()
        regex = QRegularExpression(pattern)
        cursor = self.log_display.textCursor()

        pos = cursor.position()
        found_cursor = None
        while True:
            found = document.find(regex, 0)
            if found.isNull() or found.position() >= pos:
                break
            found_cursor = found
            pos = found.position() + 1

        if found_cursor and not found_cursor.isNull():
            self._apply_quick_nav_highlight(found_cursor)
            self.log_display.setTextCursor(found_cursor)
            self.log_display.ensureCursorVisible()
        else:
            show_information("Pattern not found in the current view.")

    def _update_match_count(self) -> None:
        if self.matches:
            self.match_count_label.setText(
                f"{self.current_match_index + 1}/{len(self.matches)}"
            )
        else:
            self.match_count_label.setText("0/0")

    def search_text_changed(self, text: str) -> None:
        """Update search matches and highlight based on the search text."""
        self.matches = []
        self.current_match_index = -1
        self.highlighter.set_search_term(text)

        if not text:
            self._update_match_count()
            return

        doc = self.log_display.document()
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        while True:
            found = doc.find(text, cursor)
            if found.isNull():
                break
            self.matches.append(QTextCursor(found))
            cursor.setPosition(found.position() + len(text))
        self._update_match_count()

    def highlight_current_match(self) -> None:
        if self.matches and 0 <= self.current_match_index < len(self.matches):
            self.log_display.setTextCursor(self.matches[self.current_match_index])
            self.log_display.ensureCursorVisible()

    def goto_next_match(self) -> None:
        if not self.matches:
            return
        self.current_match_index = (self.current_match_index + 1) % len(self.matches)
        self.highlight_current_match()

    def goto_previous_match(self) -> None:
        if not self.matches:
            return
        self.current_match_index = (self.current_match_index - 1) % len(self.matches)
        self.highlight_current_match()

    file_changed_signal = Signal()

    def init_file_watcher(self) -> None:
        class PlayerLogHandler(FileSystemEventHandler):
            def __init__(self, outer: "PlayerLogTab") -> None:
                self.outer = outer
                self._last_size = 0

            def on_modified(self, event: FileSystemEvent) -> None:
                if event.src_path == str(self.outer.player_log_path):
                    self.outer.file_changed_signal.emit()

            def on_created(self, event: FileSystemEvent) -> None:
                if event.src_path == str(self.outer.player_log_path):
                    self.outer.last_log_size = 0
                    self.outer.file_changed_signal.emit()

            def on_moved(self, event: FileSystemEvent) -> None:
                if event.dest_path == str(self.outer.player_log_path):
                    self.outer.last_log_size = 0
                    self.outer.file_changed_signal.emit()

        self.file_changed_signal.connect(self.on_file_changed)

        self._observer = Observer()
        self._event_handler = PlayerLogHandler(self)
        if self.player_log_path:
            self._observer.schedule(
                self._event_handler, str(self.player_log_path.parent), recursive=False
            )
            self._observer_thread = threading.Thread(
                target=self._observer.start, daemon=True
            )
            self._observer_thread.start()

    def toggle_real_time_monitoring(self, enabled: bool) -> None:
        """Enable or disable real-time monitoring of the player log file."""
        if enabled:
            if not hasattr(self, "_observer"):
                self.init_file_watcher()
            if self._observer:
                if not self._observer_thread.is_alive():
                    logger.debug("Starting observer thread for real-time monitoring.")
                    self._observer_thread = threading.Thread(
                        target=self._observer.start, daemon=True
                    )
                    self._observer_thread.start()
        else:
            if hasattr(self, "_observer") and self._observer:
                logger.debug("Stopping observer thread for real-time monitoring.")
                self._observer.stop()

    def load_log(self) -> None:
        logger.info("Starting to load log file.")
        if not hasattr(self, "log_display") or not isinstance(
            self.log_display, QTextEdit
        ):
            logger.warning("Log display widget is not properly initialized.")
            return
        if not self.player_log_path or not self.player_log_path.exists():
            logger.warning(
                "Player.log file not found at path: {}", self.player_log_path
            )
            self.log_display.setPlainText("Player.log file not found.")
            self._update_file_info()
            return

        try:
            with open(
                self.player_log_path, "r", encoding="utf-8", errors="ignore"
            ) as f:
                content = f.read()

            new_size = len(content)
            if hasattr(self, "last_log_size"):
                if new_size > self.last_log_size:
                    self.growth_label.setText("Log is growing...")
                    logger.info("Log file is growing.")
                else:
                    self.growth_label.setText("")
            self.last_log_size = new_size

            self.current_log_content = content
            self._analyze_log_content(content)
            self._update_file_info()
            self._update_statistics()

            if self.filter_combo and self.filter_combo.currentText() != "All Entries":
                filter_type = self.filter_combo.currentText()
                mod_filter = (
                    self.mod_filter_input.text().strip().lower()
                    if self.mod_filter_input
                    else ""
                )
                lines = self.current_log_content.splitlines()
                filtered_lines = []

                mod_filter_re = (
                    re.compile(re.escape(mod_filter), re.IGNORECASE)
                    if mod_filter
                    else None
                )

                for line in lines:
                    include_line = False

                    if filter_type == "All Entries":
                        include_line = True
                    elif filter_type == "Errors Only":
                        include_line = bool(self._error_pattern.search(line))
                    elif filter_type == "Warnings & Errors":
                        include_line = bool(
                            self._error_pattern.search(line)
                            or self._warning_pattern.search(line)
                        )
                    elif filter_type == "Exceptions Only":
                        include_line = bool(self._exception_pattern.search(line))
                    elif filter_type == "Mod Issues":
                        include_line = bool(self._mod_issue_pattern.search(line))
                    elif filter_type == "Keybind Conflicts":
                        include_line = bool(self._keybind_pattern.search(line))
                    elif filter_type == "No Issues":
                        include_line = not any(
                            [
                                self._error_pattern.search(line),
                                self._warning_pattern.search(line),
                                self._exception_pattern.search(line),
                            ]
                        )

                    if include_line and mod_filter_re:
                        include_line = bool(mod_filter_re.search(line))

                    if include_line:
                        filtered_lines.append(line)

                if len(filtered_lines) == 0:
                    self.filter_combo.setCurrentText("All Entries")

            self.apply_filter()

            current_search_text = self.search_input.text() if self.search_input else ""
            if current_search_text:
                self.search_text_changed(current_search_text)

            self.matches = []
            self.current_match_index = -1
            self._update_match_count()

            self.scroll_to_end()
            logger.info("Auto-scroll to end after refresh.")

            logger.info("Log file loaded successfully.")

        except Exception as e:
            logger.error("Error reading Player.log: {}", e)
            self.log_display.setPlainText(f"Error reading Player.log: {e}")
            self._update_file_info()

    def refresh_log(self) -> None:
        if self.current_log_content:
            self.load_log()
        else:
            logger.info("No log loaded to refresh.")

    def _analyze_log_content(self, content: str) -> None:
        lines = content.splitlines()

        self.log_stats = {
            "errors": 0,
            "warnings": 0,
            "exceptions": 0,
            "total_lines": len(lines),
            "mod_issues": 0,
            "keybind_conflicts": 0,
            "info": 0,
        }

        for line in lines:
            if self._error_pattern.search(line):
                self.log_stats["errors"] += 1
            elif self._warning_pattern.search(line):
                self.log_stats["warnings"] += 1

            if self._exception_pattern.search(line):
                self.log_stats["exceptions"] += 1

            if self._mod_issue_pattern.search(line):
                self.log_stats["mod_issues"] += 1

            if self._keybind_pattern.search(line):
                self.log_stats["keybind_conflicts"] += 1

            if self._info_pattern.search(line):
                self.log_stats["info"] += 1

    def _update_file_info(self) -> None:
        if self.player_log_path and self.player_log_path.exists():
            stat = self.player_log_path.stat()
            size_mb = stat.st_size / (1024 * 1024)
            modified_time = datetime.fromtimestamp(stat.st_mtime)

            self.file_path_label.setText(f"Path: {self.player_log_path}")
            self.file_size_label.setText(f"Size: {size_mb:.2f} MB")
            self.last_modified_label.setText(
                f"Modified: {modified_time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        else:
            self.file_path_label.setText("Path: Not found")
            self.file_size_label.setText("Size: Unknown")
            self.last_modified_label.setText("Modified: Unknown")

    _cached_mod_filter_text: str = ""

    def apply_filter(self) -> None:
        """Apply the selected filter and mod name filter to the current log content."""
        if not self.current_log_content:
            return

        filter_type = self.filter_combo.currentText() if self.filter_combo else ""
        mod_filter = (
            self.mod_filter_input.text().strip().lower()
            if self.mod_filter_input
            else ""
        )
        lines = self.current_log_content.splitlines()
        filtered_lines = []

        # Cache compiled regex for mod_filter to avoid recompilation
        if mod_filter:
            if (
                not hasattr(self, "_cached_mod_filter")
                or self._cached_mod_filter_text != mod_filter
            ):
                self._cached_mod_filter = re.compile(
                    re.escape(mod_filter), re.IGNORECASE
                )
                self._cached_mod_filter_text = mod_filter
            mod_filter_re = self._cached_mod_filter
        else:
            mod_filter_re = None

        for line in lines:
            include_line = False

            if filter_type == "All Entries":
                include_line = True
            elif filter_type == "Errors Only":
                include_line = bool(self._error_pattern.search(line))
            elif filter_type == "Warnings & Errors":
                include_line = bool(
                    self._error_pattern.search(line)
                    or self._warning_pattern.search(line)
                )
            elif filter_type == "Exceptions Only":
                include_line = bool(self._exception_pattern.search(line))
            elif filter_type == "Mod Issues":
                include_line = bool(self._mod_issue_pattern.search(line))
            elif filter_type == "Keybind Conflicts":
                include_line = bool(self._keybind_pattern.search(line))
            elif filter_type == "No Issues":
                include_line = not any(
                    [
                        self._error_pattern.search(line),
                        self._warning_pattern.search(line),
                        self._exception_pattern.search(line),
                    ]
                )

            if include_line and mod_filter_re:
                include_line = bool(mod_filter_re.search(line))

            if include_line:
                filtered_lines.append(line)

        numbered_lines = [
            f"{idx + 1}: {line}" for idx, line in enumerate(filtered_lines)
        ]

        new_filtered_content = "\n".join(numbered_lines)
        # Avoid unnecessary UI update if content unchanged
        if new_filtered_content != getattr(self, "filtered_content", None):
            self.filtered_content = new_filtered_content
            self.log_display.setPlainText(self.filtered_content)

        current_search_text = self.search_input.text() if self.search_input else ""
        if current_search_text:
            self.search_text_changed(current_search_text)

    def export_log(self) -> None:
        if not self.current_log_content:
            show_warning("No log content to export.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Log",
            f"Player_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text Files (*.txt);;All Files (*)",
        )

        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(
                        f"# Player.log Export - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    )
                    f.write(f"# Total Lines: {self.log_stats['total_lines']}\n")
                    f.write(f"# Errors: {self.log_stats['errors']}\n")
                    f.write(f"# Warnings: {self.log_stats['warnings']}\n")
                    f.write(f"# Exceptions: {self.log_stats['exceptions']}\n")
                    f.write(f"# Mod Issues: {self.log_stats['mod_issues']}\n")
                    f.write(
                        f"# Keybind Conflicts: {self.log_stats['keybind_conflicts']}\n"
                    )
                    f.write(f"# Info: {self.log_stats['info']}\n")
                    f.write("#" + "=" * 50 + "\n\n")

                    content_to_export = (
                        self.filtered_content
                        if self.filter_combo
                        and self.filter_combo.currentText() != "All Entries"
                        else self.current_log_content
                    )
                    # Fix string formatting warnings by decoding bytes if needed
                    if isinstance(content_to_export, bytes):
                        content_to_export = content_to_export.decode(
                            "utf-8", errors="ignore"
                        )
                    # Fix string formatting warnings for bytes in f-string or format usage
                    if isinstance(content_to_export, bytes):
                        content_to_export = content_to_export.decode(
                            "utf-8", errors="ignore"
                        )
                    f.write(content_to_export)

                show_information(f"Log exported successfully to:\n{file_path}")
            except Exception as e:
                show_warning(f"Failed to export log:\n{str(e)}")

    def load_default_log(self) -> None:
        logger.info("Loading default game log.")
        self.player_log_path = self._get_player_log_path()
        self.load_log()

    def load_log_from_file(self) -> None:
        logger.info("Opening file dialog to load log from file.")
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Log File",
            "",
            "Log Files (*.log *.txt);;All Files (*)",
        )
        if file_path:
            logger.info("Loading log from file: {}", file_path)
            self.player_log_path = Path(file_path)
            self.load_log()

    def load_log_from_link(self) -> None:
        url, ok = QInputDialog.getText(self, "Load Log from Link", "Enter log URL:")
        if ok and url:
            logger.info("Loading log from URL: {}", url)
            try:
                import requests

                response = requests.get(url)
                response.raise_for_status()
                content = response.text

                self.current_log_content = content
                self.player_log_path = None
                self._analyze_log_content(content)
                self._update_file_info()
                self._update_statistics()
                self.apply_filter()

                self.matches = []
                self.current_match_index = -1
                self._update_match_count()

            except Exception as e:
                logger.error("Failed to load log from URL: {}", e)
                show_warning(f"Failed to load log from URL:\n{e}")

    def _apply_quick_nav_highlight(self, cursor: QTextCursor) -> None:
        existing_selections = self.log_display.extraSelections()

        selection = QTextEdit.ExtraSelection()
        setattr(selection, "cursor", cursor)
        setattr(selection, "format", self.quick_nav_highlight_format)

        new_selections = existing_selections + [selection]

        self.log_display.setExtraSelections(new_selections)

    def _update_statistics(self) -> None:
        """Update the statistics labels with the current log statistics."""
        self.total_lines_label.setText(
            f"Total Lines: {self.log_stats.get('total_lines', 0)}"
        )
        self.errors_label.setText(f"Errors: {self.log_stats.get('errors', 0)}")
        self.warnings_label.setText(f"Warnings: {self.log_stats.get('warnings', 0)}")
        self.exceptions_label.setText(
            f"Exceptions: {self.log_stats.get('exceptions', 0)}"
        )
        self.mod_issues_label.setText(
            f"Mod Issues: {self.log_stats.get('mod_issues', 0)}"
        )
        self.keybind_label.setText(
            f"Keybind Conflicts: {self.log_stats.get('keybind_conflicts', 0)}"
        )
        self.info_label.setText(f"Info: {self.log_stats.get('info', 0)}")
