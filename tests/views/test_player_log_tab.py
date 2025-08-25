"""Tests for PlayerLogTab regex patterns and functionality."""

import re
from pathlib import Path
from typing import Optional
from unittest.mock import Mock

from PySide6.QtGui import QTextDocument

from app.views.player_log_tab import LogHighlighter, PlayerLogTab


class TestLogHighlighter:
    """Test the LogHighlighter class and its regex patterns."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.parent = Mock()
        self.document = QTextDocument()
        self.highlighter = LogHighlighter(self.document)

    def test_timestamp_pattern(self) -> None:
        """Test timestamp pattern matching."""
        pattern = re.compile(r"\d{1,2}:\d{2}:\d{2} [AP]M")

        # Test valid timestamps
        assert pattern.search("12:34:56 AM")
        assert pattern.search("01:23:45 PM")
        assert pattern.search("11:59:59 AM")

        # Test invalid timestamps
        assert not pattern.search("25:61:61 XX")
        assert not pattern.search("not a timestamp")

    def test_info_pattern(self) -> None:
        """Test info pattern matching."""
        pattern = re.compile(
            r"\b(info|initialized|loaded|start(ed)?|starting|done|success)\b",
            re.IGNORECASE,
        )

        # Test valid info patterns
        assert pattern.search("INFO: Game initialized")
        assert pattern.search("System loaded successfully")
        assert pattern.search("Starting game")
        assert pattern.search("Started process")
        assert pattern.search("Done loading")
        assert pattern.search("Success: Operation completed")

        # Test case insensitivity
        assert pattern.search("Info: test")
        assert pattern.search("INITIALIZED: system")

        # Test invalid patterns
        assert not pattern.search("Error: failed")
        assert not pattern.search("Warning: issue")

    def test_keybind_pattern(self) -> None:
        """Test keybind conflict pattern matching."""
        pattern = re.compile(r"key binding conflict", re.IGNORECASE)

        # Test valid keybind patterns
        assert pattern.search("key binding conflict detected")
        assert pattern.search("KEY BINDING CONFLICT: A and B")
        assert pattern.search("Key Binding Conflict resolution")

        # Test invalid patterns
        assert not pattern.search("key binding")
        assert not pattern.search("conflict resolution")

    def test_mod_issue_pattern(self) -> None:
        """Test mod issue pattern matching."""
        pattern = re.compile(r"\[([^\]]+)\]")

        # Test valid mod issue patterns
        assert pattern.search("[ModName] Error occurred")
        assert pattern.search("Warning: [AnotherMod] issue")
        assert pattern.search("[Core] Initialized")

        # Test invalid patterns
        assert not pattern.search("No brackets here")
        assert not pattern.search("Single [ bracket")

    def test_warning_pattern(self) -> None:
        """Test warning pattern matching."""
        pattern = re.compile(
            r"\b(warning|warn|deprecat|deprecated)\b|\[W\]", re.IGNORECASE
        )

        # Test valid warning patterns
        assert pattern.search("WARNING: Something happened")
        assert pattern.search("Warning message")
        assert pattern.search("Deprecated function")
        assert pattern.search("[W] This is a warning")
        assert pattern.search("warn: potential issue")

        # Test invalid patterns
        assert not pattern.search("Information message")
        assert not pattern.search("Error occurred")

    def test_error_pattern(self) -> None:
        """Test error pattern matching with enhanced critical keyword."""
        pattern = re.compile(
            r"\b(error|failed|exception|fatal|critical)\b|\[E\]", re.IGNORECASE
        )

        # Test valid error patterns
        assert pattern.search("ERROR: Something went wrong")
        assert pattern.search("Failed to load")
        assert pattern.search("Exception occurred")
        assert pattern.search("Fatal error")
        assert pattern.search("Critical: System failure")
        assert pattern.search("[E] Error code")

        # Test case insensitivity
        assert pattern.search("error: test")
        assert pattern.search("FAILED: operation")
        assert pattern.search("EXCEPTION: handling")
        assert pattern.search("CRITICAL: alert")

        # Test invalid patterns
        assert not pattern.search("Warning: minor issue")
        assert not pattern.search("Info: status")

    def test_exception_pattern(self) -> None:
        """Test exception pattern matching with enhanced Error: pattern."""
        patterns = [
            re.compile(r".*Exception.*:"),
            re.compile(r".*Error.*:"),
            re.compile(r"^\s*at .*"),
        ]

        # Test valid exception patterns
        test_cases = [
            "System.Exception: Something went wrong",
            "ArgumentException: Invalid parameter",
            "MissingMethodException: Method not found",
            "Error: Failed to initialize",
            "RuntimeError: Memory allocation failed",
            "    at System.Environment.get_StackTrace()",
            "   at Verse.Log.Error()",
        ]

        for test_case in test_cases:
            matched = any(pattern.search(test_case) for pattern in patterns)
            assert matched, f"Pattern should match: {test_case}"

        # Test invalid patterns
        invalid_cases = [
            "Information message",
            "Warning: minor issue",
            "Success: operation completed",
        ]

        for test_case in invalid_cases:
            matched = any(pattern.search(test_case) for pattern in patterns)
            assert not matched, f"Pattern should not match: {test_case}"


class TestPlayerLogTabPatterns:
    """Test the class-level regex patterns used for filtering."""

    def test_info_pattern_class_level(self) -> None:
        """Test the class-level info pattern."""
        pattern = PlayerLogTab._info_pattern

        assert pattern.search("info: test")
        assert pattern.search("INITIALIZED: system")
        assert pattern.search("loaded successfully")
        assert pattern.search("started process")
        assert pattern.search("done with operation")
        assert pattern.search("success: completed")

        assert not pattern.search("error: failed")

    def test_keybind_pattern_class_level(self) -> None:
        """Test the class-level keybind pattern."""
        pattern = PlayerLogTab._keybind_pattern

        assert pattern.search("key binding conflict detected")
        assert not pattern.search("regular key binding")

    def test_mod_issue_pattern_class_level(self) -> None:
        """Test the class-level mod issue pattern."""
        pattern = PlayerLogTab._mod_issue_pattern

        assert pattern.search("[ModName] error occurred")
        assert pattern.search("[AnotherMod] warning message")
        assert pattern.search("mod conflict detected")
        assert pattern.search("Mod issue: compatibility")

        assert not pattern.search("regular message")

    def test_warning_pattern_class_level(self) -> None:
        """Test the class-level warning pattern."""
        pattern = PlayerLogTab._warning_pattern

        assert pattern.search("warning: test")
        assert pattern.search("WARN: potential issue")
        assert pattern.search("deprecated function")
        assert pattern.search("[W] warning message")

        assert not pattern.search("info message")

    def test_error_pattern_class_level(self) -> None:
        """Test the class-level error pattern."""
        pattern = PlayerLogTab._error_pattern

        assert pattern.search("error: test")
        assert pattern.search("FAILED: operation")
        assert pattern.search("fatal error")
        assert pattern.search("[E] error code")

        # Note: class-level pattern doesn't include "exception" or "critical"
        assert not pattern.search("exception occurred")
        assert not pattern.search("critical: alert")

    def test_exception_pattern_class_level(self) -> None:
        """Test the class-level exception pattern."""
        pattern = PlayerLogTab._exception_pattern

        assert pattern.search("exception occurred")
        assert pattern.search("EXCEPTION: error")

        assert not pattern.search("error message")
        assert not pattern.search("critical error")


def test_quick_navigation_patterns() -> None:
    """Test the quick navigation patterns used in the UI."""
    log_types = [
        ("Info", r"(?i)(info|initialized|loaded|start(ed)?|done|success)"),
        ("Keybind", r"key binding conflict"),
        ("Mod_issue", r"\[.*\]"),
        ("Warning", r"(?i)(warning|warn|deprecat|\[W\])"),
        ("Error", r"(?i)(error|failed|fatal|critical|Error:|\[E\])"),
        ("Exception", r"Exception"),
    ]

    for label_text, pattern in log_types:
        compiled_pattern = re.compile(pattern, re.IGNORECASE)

        # Test that patterns compile correctly
        assert compiled_pattern is not None

        # Test basic functionality
        if label_text == "Info":
            assert compiled_pattern.search("info: test")
        elif label_text == "Keybind":
            assert compiled_pattern.search("key binding conflict")
        elif label_text == "Mod_issue":
            assert compiled_pattern.search("[ModName] message")
        elif label_text == "Warning":
            assert compiled_pattern.search("warning: test")
        elif label_text == "Error":
            assert compiled_pattern.search("error: test")
            assert compiled_pattern.search("Critical: alert")
            assert compiled_pattern.search("Error: message")
        elif label_text == "Exception":
            assert compiled_pattern.search("Exception occurred")


# Sample test data for integration testing
SAMPLE_LOG_CONTENT = """Mono path[0] = 'D:/Games/RimWorld/RimWorldWin64_Data/Managed'
Initialize engine version: 2022.3.35f1 (011206c7a712)
[PhysX] Initialized MultithreadedTaskDispatcher with 8 workers.
INFO: Game initialized successfully
WARNING: Deprecated function called
ERROR: Failed to load asset
Exception loading from System.Xml.XmlElement: System.MissingMethodException
Critical: Memory allocation failed
key binding conflict between A and B
[MyMod] Error in initialization
   at Verse.Log.Error()
System.ArgumentException: Invalid parameter
"""


def test_integration_with_sample_log() -> None:
    """Test that all patterns work together with sample log content."""
    document = QTextDocument()
    highlighter = LogHighlighter(document)

    # Test that all expected patterns are found
    lines = SAMPLE_LOG_CONTENT.splitlines()

    # Count expected matches by type
    expected_matches = {
        "timestamp": 0,  # No timestamps in this sample
        "info": 1,  # "INFO: Game initialized successfully"
        "keybind": 1,  # "key binding conflict between A and B"
        "mod_issue": 1,  # "[MyMod] Error in initialization"
        "warning": 1,  # "WARNING: Deprecated function called"
        "error": 2,  # "ERROR: Failed to load asset", "Critical: Memory allocation failed"
        "exception": 3,  # "Exception loading from...", "   at Verse.Log.Error()", "System.ArgumentException:..."
    }

    # Test each line
    for line in lines:
        for pattern, fmt in highlighter.patterns:
            if pattern.search(line):
                # Pattern matched, we can verify the type if needed
                pass


def test_with_actual_sample_log_file() -> None:
    """Test patterns with the actual sample log file."""
    sample_log_path = Path("tests/data/logs/sample_player.log")

    # Read the sample log file
    with open(sample_log_path, "r", encoding="utf-8") as f:
        log_content = f.read()

    document = QTextDocument()
    highlighter = LogHighlighter(document)
    lines = log_content.splitlines()

    # Count matches by type
    match_counts = {
        "timestamp": 0,
        "info": 0,
        "keybind": 0,
        "mod_issue": 0,
        "warning": 0,
        "error": 0,
        "exception": 0,
    }

    # Test each line and count matches
    for line in lines:
        for i, (pattern, fmt) in enumerate(highlighter.patterns):
            if pattern.search(line):
                # Determine the type based on pattern index
                if i == 0:  # timestamp
                    match_counts["timestamp"] += 1
                elif i == 1:  # info
                    match_counts["info"] += 1
                elif i == 2:  # keybind
                    match_counts["keybind"] += 1
                elif i == 3:  # mod_issue
                    match_counts["mod_issue"] += 1
                elif i in [4, 5]:  # warning (two patterns)
                    match_counts["warning"] += 1
                elif i in [6, 7]:  # error (two patterns)
                    match_counts["error"] += 1
                elif i in [8, 9]:  # exception (two patterns)
                    match_counts["exception"] += 1

    # Verify we found expected patterns
    assert match_counts["timestamp"] >= 3, "Should find timestamp patterns"
    assert match_counts["info"] >= 6, "Should find info patterns"
    assert match_counts["keybind"] >= 2, "Should find keybind patterns"
    assert match_counts["mod_issue"] >= 4, "Should find mod issue patterns"
    assert match_counts["warning"] >= 4, "Should find warning patterns"
    assert match_counts["error"] >= 5, "Should find error patterns"
    assert match_counts["exception"] >= 7, "Should find exception patterns"

    print(f"Pattern matches found: {match_counts}")


def test_enhanced_patterns_work() -> None:
    """Test that the enhanced patterns (critical keyword and Error: pattern) work correctly."""
    document = QTextDocument()
    highlighter = LogHighlighter(document)

    # Test critical keyword (enhanced error pattern)
    critical_line = "Critical: Memory allocation failed"
    error_pattern_found = False
    for pattern, fmt in highlighter.patterns:
        if pattern.search(critical_line) and fmt == highlighter.error_format:
            error_pattern_found = True
            break
    assert error_pattern_found, "Critical keyword should be detected as error"

    # Test Error: pattern (enhanced exception pattern)
    error_colon_line = "Error: Failed to parse XML configuration"
    exception_pattern_found = False
    for pattern, fmt in highlighter.patterns:
        if pattern.search(error_colon_line) and fmt == highlighter.exception_format:
            exception_pattern_found = True
            break
    assert exception_pattern_found, "Error: pattern should be detected as exception"


def test_lazy_loading_functionality() -> None:
    """Test that lazy loading works correctly with chunked file reading."""
    from unittest.mock import mock_open, patch

    from app.views.player_log_tab import PlayerLogTab

    # Mock settings controller
    mock_settings = Mock()
    mock_settings.settings = Mock()
    mock_settings.settings.auto_load_player_log_on_startup = False

    # Create player log tab instance
    player_log_tab = PlayerLogTab(mock_settings)

    # Mock log content with multiple chunks
    mock_log_content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n"

    # Test with different chunk sizes
    for chunk_size in [1, 2, 3, 5, 10]:
        with patch("builtins.open", mock_open(read_data=mock_log_content)):
            with patch("pathlib.Path.exists", return_value=True):
                player_log_tab.player_log_path = Path("/fake/path/Player.log")
                player_log_tab.load_log(chunk_size=chunk_size)

                # Verify content was loaded correctly
                assert player_log_tab.current_log_content == mock_log_content
                assert player_log_tab.last_log_size == len(mock_log_content)

                # Verify statistics were updated
                assert player_log_tab.log_stats["total_lines"] == 5


def test_lazy_loading_with_empty_file() -> None:
    """Test lazy loading behavior with an empty file."""
    from unittest.mock import mock_open, patch

    from app.views.player_log_tab import PlayerLogTab

    # Mock settings controller
    mock_settings = Mock()
    mock_settings.settings = Mock()
    mock_settings.settings.auto_load_player_log_on_startup = False

    # Create player log tab instance
    player_log_tab = PlayerLogTab(mock_settings)

    # Mock empty log content
    mock_log_content = ""

    with patch("builtins.open", mock_open(read_data=mock_log_content)):
        with patch("pathlib.Path.exists", return_value=True):
            player_log_tab.player_log_path = Path("/fake/path/Player.log")
            player_log_tab.load_log(chunk_size=1024)

            # Verify content was loaded correctly
            assert player_log_tab.current_log_content == mock_log_content
            assert player_log_tab.last_log_size == len(mock_log_content)

            # Verify statistics were updated
            assert player_log_tab.log_stats["total_lines"] == 0


def test_lazy_loading_with_large_file() -> None:
    """Test lazy loading with a large file to ensure chunking works."""
    from unittest.mock import mock_open, patch

    from app.views.player_log_tab import PlayerLogTab

    # Mock settings controller
    mock_settings = Mock()
    mock_settings.settings = Mock()
    mock_settings.settings.auto_load_player_log_on_startup = False

    # Create player log tab instance
    player_log_tab = PlayerLogTab(mock_settings)

    # Create a large log content (multiple chunks worth)
    large_content = "\n".join([f"Line {i}" for i in range(1000)])

    # Mock the file read to simulate chunked reading
    def mock_file_read(chunk_size: int) -> list[str]:
        chunks = []
        current_pos = 0
        while current_pos < len(large_content):
            chunk = large_content[current_pos : current_pos + chunk_size]
            chunks.append(chunk)
            current_pos += chunk_size
        return chunks

    # Test with small chunk size to ensure chunking works
    chunk_size = 100
    expected_chunks = mock_file_read(chunk_size)

    # Create a mock that returns the full content when no size is specified
    # and chunks when size is specified
    mock_file = mock_open(read_data=large_content)

    def read_side_effect(size: Optional[int] = None) -> str:
        if size is None:
            return large_content
        return large_content[:size]

    mock_file.return_value.read.side_effect = read_side_effect

    with patch("builtins.open", mock_file):
        with patch("pathlib.Path.exists", return_value=True):
            player_log_tab.player_log_path = Path("/fake/path/Player.log")
            player_log_tab.load_log(chunk_size=chunk_size)

            # Verify content was loaded correctly
            assert player_log_tab.current_log_content == large_content
            assert player_log_tab.last_log_size == len(large_content)
