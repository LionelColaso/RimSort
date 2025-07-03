import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.controllers.settings_controller import SettingsController
from app.views.dialogue import show_information, show_warning


class LogHighlighter(QSyntaxHighlighter):
    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)

        # Define color formats
        self.error_format = QTextCharFormat()
        self.error_format.setForeground(QColor("#FF4444"))
        self.error_format.setFontWeight(QFont.Weight.Bold)

        self.warning_format = QTextCharFormat()
        self.warning_format.setForeground(QColor("#FF8C00"))
        self.warning_format.setFontWeight(QFont.Weight.Bold)

        self.exception_format = QTextCharFormat()
        self.exception_format.setForeground(QColor("#DC143C"))
        self.exception_format.setBackground(QColor("#FFEEEE"))

        self.info_format = QTextCharFormat()
        self.info_format.setForeground(QColor("#00BFFF"))

        self.mod_format = QTextCharFormat()
        self.mod_format.setForeground(QColor("#4169E1"))

        self.timestamp_format = QTextCharFormat()
        self.timestamp_format.setForeground(QColor("#808080"))

        self.keybind_format = QTextCharFormat()
        self.keybind_format.setForeground(QColor("#FFD700"))
        self.keybind_format.setFontWeight(QFont.Weight.Bold)

        self.search_format = QTextCharFormat()

        self.search_term: str | None = None
        self._search_regex: re.Pattern[str] | None = None  # Cache compiled regex
        # Define patterns with priority (higher index = higher priority)
        self.patterns = [
            # Keybind conflicts
            (re.compile(r"key binding conflict", re.IGNORECASE), self.keybind_format),
            # Timestamps
            (re.compile(r"\d{1,2}:\d{2}:\d{2} [AP]M"), self.timestamp_format),
            # Mod tags
            (re.compile(r"\[([^\]]+)\]"), self.mod_format),
            # Info
            (
                re.compile(
                    r"(?i)\b(info|initialized|loaded|start(ed)?|done|success)\b"
                ),
                self.info_format,
            ),
            # Warnings
            (re.compile(r"(?i)\b(warning|warn|deprecat)\b"), self.warning_format),
            (re.compile(r"\[W\]"), self.warning_format),
            # Errors
            (
                re.compile(r"(?i)\b(error|failed|exception|fatal|critical)\b"),
                self.error_format,
            ),
            (re.compile(r"\[E\]"), self.error_format),
            # Exceptions
            (re.compile(r".*Exception.*:|.*Error.*:"), self.exception_format),
            (re.compile(r"^\s*at .*"), self.exception_format),
        ]

        self.set_search_highlight_color(QColor("#FFD700"))  # Default yellow

    def set_search_highlight_color(self, color: QColor) -> None:
        self.search_format.setUnderlineColor(color)
        self.search_format.setUnderlineStyle(
            QTextCharFormat.UnderlineStyle.WaveUnderline
        )
        self.rehighlight()

        # Define patterns with priority (higher index = higher priority)
        self.patterns = [
            # Keybind conflict highlight
            (
                re.compile(r"key binding conflict", re.IGNORECASE),
                self._make_format("#FFD700", bold=True),
            ),
            # Timestamps
            (re.compile(r"\d{1,2}:\d{2}:\d{2} [AP]M"), self.timestamp_format),
            # Mod names in brackets
            (re.compile(r"\[([^\]]+)\]"), self.mod_format),
            # Warning patterns
            (re.compile(r"(?i)\b(warning|warn|deprecat)\b"), self.warning_format),
            (re.compile(r"\[W\]"), self.warning_format),
            # Error patterns - higher priority than warnings
            (
                re.compile(r"(?i)\b(error|failed|exception|fatal|critical)\b"),
                self.error_format,
            ),
            (re.compile(r"\[E\]"), self.error_format),
            # Exception stack traces
            (re.compile(r".*Exception.*:|.*Error.*:"), self.exception_format),
            (re.compile(r"^\s*at .*"), self.exception_format),
        ]

        # self.search_term is already defined in __init__, do not redefine here

    def set_search_term(self, term: str | None) -> None:
        self.search_term = term
        if term:
            try:
                self._search_regex = re.compile(re.escape(term), re.IGNORECASE)
            except Exception:
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
        # Color code search matches first (highest priority)
        if self._search_regex:
            try:
                for match in self._search_regex.finditer(text):
                    start, end = match.span()
                    self.setFormat(start, end - start, self.search_format)
            except Exception:
                pass
        # Then apply all other patterns
        for pattern, fmt in self.patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                self.setFormat(start, end - start, fmt)


class PlayerLogTab(QWidget):
    def set_search_highlight_color(self, color: QColor) -> None:
        self.highlighter.set_search_highlight_color(color)

    matches: list[QTextCursor]
    last_log_size: int

    def __init__(self, settings_controller: SettingsController) -> None:
        super().__init__()
        self.settings_controller = settings_controller
        self.player_log_path: Optional[Path] = None
        self.current_log_content: str = ""
        self.log_stats: dict[str, int] = {
            "errors": 0,
            "warnings": 0,
            "exceptions": 0,
            "total_lines": 0,
            "mod_issues": 0,
        }
        # Only declare types, do not assign before init_ui()
        self.highlighter: LogHighlighter
        self.log_display: QTextEdit
        # Ensure UI is initialized before any log access
        self.init_ui()  # This creates self.log_display and self.highlighter
        self.player_log_path = self._get_player_log_path()
        self.setup_autorefresh()

    def clear_log_display(self) -> None:
        """Clear the log display widget."""
        self.log_display.clear()

    def scroll_to_end(self) -> None:
        """Scroll to the end of the log display."""
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

    # ...existing code...

    def pick_search_highlight_color(self) -> None:
        from PySide6.QtWidgets import QColorDialog

        color = QColorDialog.getColor(
            self.highlighter.search_format.underlineColor(),
            self,
            "Pick Search Highlight Color",
        )
        if color.isValid():
            self.set_search_highlight_color(color)

    # ...existing code...

    def init_ui(self) -> None:
        self.main_layout = QVBoxLayout()

        # Create splitter for resizable panels
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QSizePolicy

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        )

        # Left panel for controls and statistics
        self.left_panel = QWidget()
        self.left_panel.setMaximumWidth(400)
        self.left_panel.setMinimumWidth(200)
        self.left_panel.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        )
        self.left_layout = QVBoxLayout(self.left_panel)
        # Right panel for log display
        self.right_panel = QWidget()
        self.right_panel.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        )
        self.right_layout = QVBoxLayout(self.right_panel)

        # Log display
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFont(QFont("Consolas", 10))
        self.log_display.setMinimumSize(400, 200)
        self.log_display.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        )
        self.log_display.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.log_display.customContextMenuRequested.connect(self.show_context_menu)
        self.right_layout.addWidget(self.log_display)
        # Initialize the log highlighter
        self.highlighter = LogHighlighter(self.log_display.document())

        # Add panels to splitter
        self.splitter.addWidget(self.left_panel)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setSizes([400, 1000])  # Set initial sizes
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        self.main_layout.addWidget(self.splitter)
        self.setLayout(self.main_layout)
        # --- All widgets and layouts are now created above ---

        # File info group
        file_info_group = QGroupBox("Log File Information")
        file_info_layout = QVBoxLayout(file_info_group)

        self.file_path_label = QLabel("Path: Not found")
        self.file_path_label.setWordWrap(True)
        file_info_layout.addWidget(self.file_path_label)

        self.file_size_label = QLabel("Size: Unknown")
        file_info_layout.addWidget(self.file_size_label)

        self.last_modified_label = QLabel("Modified: Unknown")
        file_info_layout.addWidget(self.last_modified_label)

        # Log growth indicator
        self.growth_label = QLabel("")
        self.growth_label.setStyleSheet("color: green; font-weight: bold;")
        file_info_layout.addWidget(self.growth_label)

        self.left_layout.addWidget(file_info_group)

        # Controls group
        controls_group = QGroupBox("Controls")
        controls_layout = QVBoxLayout(controls_group)

        # Refresh and export buttons
        button_layout = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.load_log)
        self.export_button = QPushButton("Export")
        self.export_button.clicked.connect(self.export_log)
        self.clear_button = QPushButton("Clear Log Display")
        self.clear_button.clicked.connect(self.clear_log_display)
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(self.export_button)
        button_layout.addWidget(self.clear_button)
        controls_layout.addLayout(button_layout)

        # Auto-refresh checkbox
        self.auto_refresh_checkbox = QCheckBox("Auto-refresh (15s)")
        self.auto_refresh_checkbox.setChecked(True)
        self.auto_refresh_checkbox.toggled.connect(self.toggle_auto_refresh)
        controls_layout.addWidget(self.auto_refresh_checkbox)

        # Pause auto-refresh button
        self.pause_refresh_button = QPushButton("Pause Auto-Refresh")
        self.pause_refresh_button.setCheckable(True)
        self.pause_refresh_button.toggled.connect(self.toggle_auto_refresh)
        controls_layout.addWidget(self.pause_refresh_button)

        # Log level filter
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter:"))
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
        self.filter_combo.currentTextChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.filter_combo)
        controls_layout.addLayout(filter_layout)

        # Mod filter
        mod_filter_layout = QHBoxLayout()
        mod_filter_layout.addWidget(QLabel("Mod/Tag:"))
        self.mod_filter_input = QLineEdit()
        self.mod_filter_input.setPlaceholderText("e.g. NQoL, RimHUD, [Ore Yields]")
        self.mod_filter_input.textChanged.connect(self.apply_filter)
        mod_filter_layout.addWidget(self.mod_filter_input)
        controls_layout.addLayout(mod_filter_layout)

        self.left_layout.addWidget(controls_group)

        # Statistics group
        stats_group = QGroupBox("Log Statistics")
        stats_layout = QVBoxLayout(stats_group)

        self.total_lines_label = QLabel("Total Lines: 0")
        self.errors_label = QLabel("Errors: 0")
        self.warnings_label = QLabel("Warnings: 0")
        self.exceptions_label = QLabel("Exceptions: 0")
        self.mod_issues_label = QLabel("Mod Issues: 0")
        self.keybind_label = QLabel("Keybind Conflicts: 0")
        self.info_label = QLabel("Info: 0")

        for label in [
            self.total_lines_label,
            self.errors_label,
            self.warnings_label,
            self.exceptions_label,
            self.mod_issues_label,
            self.keybind_label,
            self.info_label,
        ]:
            stats_layout.addWidget(label)

        self.left_layout.addWidget(stats_group)

        # Quick navigation group (improved layout)
        nav_group = QGroupBox("Quick Navigation")
        nav_layout = QGridLayout(nav_group)
        self.goto_error_btn = QPushButton("Next Error")
        self.goto_error_btn.setToolTip("Jump to next error entry")
        self.goto_error_btn.clicked.connect(
            lambda: self.goto_first_pattern(r"(?i)(error|failed|fatal|critical|\[E\])")
        )
        self.goto_warning_btn = QPushButton("Next Warning")
        self.goto_warning_btn.setToolTip("Jump to next warning entry")
        self.goto_warning_btn.clicked.connect(
            lambda: self.goto_first_pattern(r"(?i)(warning|warn|deprecat|\[W\])")
        )
        self.goto_exception_btn = QPushButton("Next Exception")
        self.goto_exception_btn.setToolTip("Jump to next exception entry")
        self.goto_exception_btn.clicked.connect(
            lambda: self.goto_first_pattern(r"Exception|Error:")
        )
        self.goto_mod_btn = QPushButton("Next Mod Issue")
        self.goto_mod_btn.setToolTip("Jump to next mod issue entry")
        self.goto_mod_btn.clicked.connect(lambda: self.goto_first_pattern(r"\[.*\]"))
        self.goto_keybind_btn = QPushButton("Next Keybind Conflict")
        self.goto_keybind_btn.setToolTip("Jump to next keybind conflict entry")
        self.goto_keybind_btn.clicked.connect(
            lambda: self.goto_first_pattern(r"key binding conflict")
        )
        self.goto_info_btn = QPushButton("Next Info")
        self.goto_info_btn.setToolTip("Jump to next info entry")
        self.goto_info_btn.clicked.connect(
            lambda: self.goto_first_pattern(
                r"(?i)(info|initialized|loaded|start(ed)?|done|success)"
            )
        )

        self.scroll_to_end_btn = QPushButton("Scroll to End")
        self.scroll_to_end_btn.setToolTip("Scroll to the end of the log display")
        self.scroll_to_end_btn.clicked.connect(self.scroll_to_end)
        nav_layout.addWidget(self.scroll_to_end_btn, 3, 0, 1, 2)

        nav_layout.addWidget(self.goto_error_btn, 0, 0)
        nav_layout.addWidget(self.goto_warning_btn, 0, 1)
        nav_layout.addWidget(self.goto_exception_btn, 1, 0)
        nav_layout.addWidget(self.goto_mod_btn, 1, 1)
        nav_layout.addWidget(self.goto_keybind_btn, 2, 0)
        nav_layout.addWidget(self.goto_info_btn, 2, 1)

        self.left_layout.addWidget(nav_group)

        # Now that ALL widgets and layouts are created, load the log (last line)
        self.load_log()

        # Search group
        search_group = QGroupBox("Search")
        search_layout = QVBoxLayout(search_group)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search log entries...")
        # Debounce timer for search
        from PySide6.QtCore import QTimer

        self._search_debounce_timer = QTimer(self)
        self._search_debounce_timer.setSingleShot(True)
        self._search_debounce_timer.setInterval(300)  # 300ms debounce
        self.search_input.textChanged.connect(self._on_search_text_changed_debounced)
        self._search_debounce_timer.timeout.connect(self._do_search_text_changed)
        search_layout.addWidget(self.search_input)

        # Add search highlight color picker
        color_button_layout = QHBoxLayout()
        self.color_picker_button = QPushButton("Search Highlight Color")
        self.color_picker_button.setToolTip("Pick color for search result highlighting")
        self.color_picker_button.clicked.connect(self.pick_search_highlight_color)
        color_button_layout.addWidget(self.color_picker_button)
        color_button_layout.addStretch()
        search_layout.addLayout(color_button_layout)

        search_nav_layout = QHBoxLayout()
        self.prev_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        self.match_count_label = QLabel("0/0")

        self.prev_button.clicked.connect(self.goto_previous_match)
        self.next_button.clicked.connect(self.goto_next_match)

        search_nav_layout.addWidget(self.prev_button)
        search_nav_layout.addWidget(self.next_button)
        search_nav_layout.addWidget(self.match_count_label)
        search_layout.addLayout(search_nav_layout)

        self.left_layout.addWidget(search_group)
        self.left_layout.addStretch()  # Push everything to top

        # (Removed duplicate/incorrect right_panel and log_display block)

    def _on_search_text_changed_debounced(self, text: str) -> None:
        self._pending_search_text = text
        self._search_debounce_timer.start()

    def _do_search_text_changed(self) -> None:
        text = getattr(self, "_pending_search_text", "")
        self.search_text_changed(text)

    from PySide6.QtCore import QPoint

    def show_context_menu(self, pos: QPoint) -> None:
        menu = self.log_display.createStandardContextMenu()
        cursor = self.log_display.textCursor()
        if cursor.hasSelection():
            menu.addSeparator()
            copy_action = menu.addAction("Copy Selection")
            copy_action.triggered.connect(lambda: self.log_display.copy())
        menu.exec(self.log_display.mapToGlobal(pos))

    def goto_prev_next_pattern(self, pattern: str, prev: bool = False) -> None:
        """Navigate to the previous or next occurrence of a regex pattern."""
        from PySide6.QtCore import QRegularExpression

        document = self.log_display.document()
        regex = QRegularExpression(pattern)
        cursor = self.log_display.textCursor()
        start_pos = cursor.position()
        found = None
        # Avoid infinite loop by limiting search attempts
        max_attempts = document.blockCount()
        attempts = 0
        if prev:
            pos = start_pos - 1
            while pos >= 0 and attempts < max_attempts:
                c = document.find(regex, pos, QTextDocument.FindFlag.FindBackward)
                if c.isNull() or c.position() == pos:
                    break
                found = c
                pos = c.position() - 1
                attempts += 1
            if found:
                self.log_display.setTextCursor(found)
                self.log_display.ensureCursorVisible()
            else:
                show_information("No previous match found.")
        else:
            pos = start_pos + 1
            while pos < document.characterCount() and attempts < max_attempts:
                c = document.find(regex, pos)
                if c.isNull() or c.position() == pos:
                    break
                found = c
                break
                attempts += 1
            if found:
                self.log_display.setTextCursor(found)
                self.log_display.ensureCursorVisible()
            else:
                show_information("No next match found.")

    def load_log(self) -> None:
        if not hasattr(self, "log_display") or not isinstance(
            self.log_display, QTextEdit
        ):
            return
        if not self.player_log_path or not self.player_log_path.exists():
            self.log_display.setPlainText("Player.log file not found.")
            self._update_file_info()
            return

        try:
            with open(
                self.player_log_path, "r", encoding="utf-8", errors="ignore"
            ) as f:
                content = f.read()

            # Log growth indicator
            new_size = len(content)
            if hasattr(self, "last_log_size"):
                if new_size > self.last_log_size:
                    self.growth_label.setText("Log is growing...")
                else:
                    self.growth_label.setText("")
            self.last_log_size = new_size

            self.current_log_content = content
            self._analyze_log_content(content)
            self._update_file_info()
            self._update_statistics()
            self.apply_filter()  # Apply current filter

            self.matches = []
            self.current_match_index = -1
            self._update_match_count()

        except Exception as e:
            if hasattr(self, "log_display") and isinstance(self.log_display, QTextEdit):
                self.log_display.setPlainText(f"Error reading Player.log: {e}")
            self._update_file_info()

    def _analyze_log_content(self, content: str) -> None:
        """Analyze log content and extract statistics."""
        lines = content.split("\n")

        # Reset stats
        self.log_stats = {
            "errors": 0,
            "warnings": 0,
            "exceptions": 0,
            "total_lines": len(lines),
            "mod_issues": 0,
        }

        # Count different types of log entries
        for line in lines:
            line_lower = line.lower()

            # Count errors
            if (
                "[e]" in line_lower
                or "error" in line_lower
                or "failed" in line_lower
                or "fatal" in line_lower
            ):
                self.log_stats["errors"] += 1

            # Count warnings
            elif (
                "[w]" in line_lower
                or "warning" in line_lower
                or "warn" in line_lower
                or "deprecat" in line_lower
            ):
                self.log_stats["warnings"] += 1

            # Count exceptions
            if "exception" in line_lower:
                self.log_stats["exceptions"] += 1

            # Count mod-related issues
            if (
                (
                    "[" in line
                    and "]" in line
                    and (
                        "error" in line_lower
                        or "warning" in line_lower
                        or "exception" in line_lower
                    )
                )
                or "mod" in line_lower
                and ("conflict" in line_lower or "issue" in line_lower)
            ):
                self.log_stats["mod_issues"] += 1

    def _update_file_info(self) -> None:
        """Update file information labels."""
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

    def _update_statistics(self) -> None:
        """Update statistics labels."""
        self.total_lines_label.setText(f"Total Lines: {self.log_stats['total_lines']}")
        self.errors_label.setText(f"Errors: {self.log_stats['errors']}")
        self.warnings_label.setText(f"Warnings: {self.log_stats['warnings']}")
        self.exceptions_label.setText(f"Exceptions: {self.log_stats['exceptions']}")
        self.mod_issues_label.setText(f"Mod Issues: {self.log_stats['mod_issues']}")

    def apply_filter(self) -> None:
        """Apply the selected filter to the log content."""
        if not self.current_log_content:
            return

        filter_type = self.filter_combo.currentText()
        mod_filter = self.mod_filter_input.text().strip().lower()
        lines = self.current_log_content.split("\n")
        filtered_lines = []

        for line in lines:
            line_lower = line.lower()
            include_line = False

            if filter_type == "All Entries":
                include_line = True
            elif filter_type == "Errors Only":
                include_line = (
                    "[e]" in line_lower
                    or "error" in line_lower
                    or "failed" in line_lower
                    or "fatal" in line_lower
                )
            elif filter_type == "Warnings & Errors":
                include_line = (
                    "[e]" in line_lower
                    or "error" in line_lower
                    or "failed" in line_lower
                    or "fatal" in line_lower
                    or "[w]" in line_lower
                    or "warning" in line_lower
                    or "warn" in line_lower
                )
            elif filter_type == "Exceptions Only":
                include_line = "exception" in line_lower
            elif filter_type == "Mod Issues":
                include_line = (
                    (
                        "[" in line
                        and "]" in line
                        and (
                            "error" in line_lower
                            or "warning" in line_lower
                            or "exception" in line_lower
                        )
                    )
                    or "mod" in line_lower
                    and ("conflict" in line_lower or "issue" in line_lower)
                )
            elif filter_type == "Keybind Conflicts":
                include_line = "key binding conflict" in line_lower
            elif filter_type == "No Issues":
                include_line = not any(
                    keyword in line_lower
                    for keyword in [
                        "error",
                        "warning",
                        "exception",
                        "failed",
                        "fatal",
                        "[e]",
                        "[w]",
                    ]
                )

            # Mod/tag filter
            if include_line and mod_filter:
                include_line = mod_filter in line_lower

            if include_line:
                filtered_lines.append(line)

        self.filtered_content = "\n".join(filtered_lines)
        self.log_display.setPlainText(self.filtered_content)

    def toggle_auto_refresh(self, enabled: bool) -> None:
        """Toggle auto-refresh functionality."""
        if enabled:
            self.timer.start()
        else:
            self.timer.stop()

    def export_log(self) -> None:
        """Export the current log content to a file."""
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
                    # Write statistics header
                    f.write(
                        f"# Player.log Export - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    )
                    f.write(f"# Total Lines: {self.log_stats['total_lines']}\n")
                    f.write(f"# Errors: {self.log_stats['errors']}\n")
                    f.write(f"# Warnings: {self.log_stats['warnings']}\n")
                    f.write(f"# Exceptions: {self.log_stats['exceptions']}\n")
                    f.write(f"# Mod Issues: {self.log_stats['mod_issues']}\n")
                    f.write("#" + "=" * 50 + "\n\n")

                    # Write the actual content (filtered if applied)
                    content_to_export = (
                        self.filtered_content
                        if self.filter_combo.currentText() != "All Entries"
                        else self.current_log_content
                    )
                    f.write(content_to_export)

                show_information(f"Log exported successfully to:\n{file_path}")
            except Exception as e:
                show_warning(f"Failed to export log:\n{str(e)}")

    def goto_first_pattern(self, pattern: str) -> None:
        """Navigate to the first occurrence of a regex pattern."""
        # Use QRegularExpression for compatibility with QTextDocument.find
        from PySide6.QtCore import QRegularExpression

        document = self.log_display.document()
        regex = QRegularExpression(pattern)
        cursor = document.find(regex)

        if not cursor.isNull():
            self.log_display.setTextCursor(cursor)
            self.log_display.ensureCursorVisible()
        else:
            show_information("Pattern not found in the current view.")

    def goto_end(self) -> None:
        """Navigate to the end of the log."""
        cursor = self.log_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_display.setTextCursor(cursor)
        self.log_display.ensureCursorVisible()

    def setup_autorefresh(self) -> None:
        self.timer = QTimer(self)
        self.timer.setInterval(15000)  # 15 seconds
        self.timer.timeout.connect(self.load_log)
        self.timer.start()

    def _update_match_count(self) -> None:
        """Update the match count label."""
        if self.matches:
            self.match_count_label.setText(
                f"{self.current_match_index + 1}/{len(self.matches)}"
            )
        else:
            self.match_count_label.setText("0/0")

    def search_text_changed(self, text: str) -> None:
        """Handle search text changes, highlight and index matches for navigation."""
        self.matches = []
        self.current_match_index = -1
        self.highlighter.set_search_term(text)

        # Find all matches in the current log display
        if text:
            doc = self.log_display.document()
            cursor = QTextCursor(doc)
            # Start at the beginning
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            while True:
                found = doc.find(text, cursor)
                if found.isNull():
                    break
                self.matches.append(QTextCursor(found))
                # Move past this match
                cursor.setPosition(found.position() + len(text))
        self._update_match_count()

    def highlight_current_match(self) -> None:
        # Move the cursor to the current match (if any)
        if self.matches and 0 <= self.current_match_index < len(self.matches):
            self.log_display.setTextCursor(self.matches[self.current_match_index])
            self.log_display.ensureCursorVisible()

    def goto_next_match(self) -> None:
        """Navigate to the next search match."""
        if not self.matches:
            return
        self.current_match_index = (self.current_match_index + 1) % len(self.matches)
        self.highlight_current_match()

    def goto_previous_match(self) -> None:
        """Navigate to the previous search match."""
        if not self.matches:
            return
        self.current_match_index = (self.current_match_index - 1) % len(self.matches)
        self.highlight_current_match()
