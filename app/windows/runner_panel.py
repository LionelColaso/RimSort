import os
from platform import system
from re import compile, findall, search
from typing import Any, Sequence

import psutil
from loguru import logger
from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtGui import QCloseEvent, QFont, QIcon, QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QProgressBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.utils.app_info import AppInfo
from app.utils.gui_info import GUIInfo
from app.utils.steam.webapi.wrapper import (
    ISteamRemoteStorage_GetPublishedFileDetails,
)
from app.views.dialogue import (
    BinaryChoiceDialog,
    show_dialogue_conditional,
    show_dialogue_file,
)


class RunnerPanel(QWidget):
    """
    A generic, read-only panel that can be used to display output from something.
    It also has a built-in QProcess functionality.
    """

    closing_signal = Signal()
    steamcmd_downloader_signal = Signal(list)

    def __init__(
        self,
        todds_dry_run_support: bool = False,
        steamcmd_download_tracking: list[str] = [],
        steam_db: dict[str, Any] = {},
    ):
        super().__init__()

        logger.debug("Initializing RunnerPanel")
        self.ansi_escape = compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
        self.system = system()
        self.installEventFilter(self)

        # Support for tracking SteamCMD download progress
        self.previous_line = ""
        self.steamcmd_download_tracking = steamcmd_download_tracking
        self.steam_db = steam_db

        # The "runner"
        self.text = QPlainTextEdit()
        self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())
        self.text.setReadOnly(True)
        # Font cfg by platform
        if self.system == "Darwin":
            self.text.setFont(QFont("Monaco"))
        elif self.system == "Linux":
            self.text.setFont(QFont("DejaVu Sans Mono"))
        elif self.system == "Windows":
            self.text.setFont(QFont("Cascadia Code"))

        # A runner can have a process executed and display it's output
        self.process = QProcess()
        self.process_killed = False
        self.process_last_output = ""
        self.process_last_command = ""
        self.process_last_args: Sequence[str] = []
        self.steamcmd_current_pfid: str | None = None
        self.todds_dry_run_support = todds_dry_run_support

        # SET STYLESHEET
        self.text.setObjectName("RunnerPanelText")
        self.setObjectName("RunnerPanel")

        # CREATE WIDGETS
        # Clear btn
        self.clear_runner_icon = QIcon(
            str(AppInfo().theme_data_folder / "default-icons" / "clear.png")
        )
        self.clear_runner_button = QToolButton()
        self.clear_runner_button.setIcon(self.clear_runner_icon)
        self.clear_runner_button.clicked.connect(self._do_clear_runner)
        self.clear_runner_button.setToolTip(
            self.tr("Clear the text currently displayed by the runner")
        )
        # Restart btn
        self.restart_process_icon = QIcon(
            str(AppInfo().theme_data_folder / "default-icons" / "restart_process.png")
        )
        self.restart_process_button = QToolButton()
        self.restart_process_button.setIcon(self.restart_process_icon)
        self.restart_process_button.clicked.connect(self._do_restart_process)
        self.restart_process_button.setToolTip(
            self.tr("Re-run the process last used by the runner")
        )
        self.restart_process_button.hide()  # Hide this by default - it will be enabled if self.execute()
        # Kill btn
        self.kill_process_icon = QIcon(
            str(AppInfo().theme_data_folder / "default-icons" / "kill_process.png")
        )
        self.kill_process_button = QToolButton()
        self.kill_process_button.setIcon(self.kill_process_icon)
        self.kill_process_button.clicked.connect(self._do_kill_process)
        self.kill_process_button.setToolTip(
            self.tr("Kill a process currently being executed by the runner")
        )
        self.kill_process_button.hide()  # Hide this by default - it will be enabled if self.execute()
        # Save process output btn
        self.save_runner_icon = QIcon(
            str(AppInfo().theme_data_folder / "default-icons" / "save_output.png")
        )
        self.save_runner_output_button = QToolButton()
        self.save_runner_output_button.setIcon(self.save_runner_icon)
        self.save_runner_output_button.clicked.connect(self._do_save_runner_output)
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        self.progress_bar.setObjectName("default")
        # CREATE LAYOUTS
        self.main_layout = QHBoxLayout()
        self.runner_layout = QVBoxLayout()
        self.actions_bar_layout = QVBoxLayout()
        # ADD WIDGETS TO LAYOUTS
        self.runner_layout.addWidget(self.progress_bar)
        self.runner_layout.addWidget(self.text)
        self.actions_bar_layout.addWidget(self.clear_runner_button)
        self.actions_bar_layout.addWidget(self.restart_process_button)
        self.actions_bar_layout.addWidget(self.kill_process_button)
        self.actions_bar_layout.addWidget(self.save_runner_output_button)
        # ADD LAYOUTS TO LAYOUTS
        self.main_layout.addLayout(self.runner_layout)
        self.main_layout.addLayout(self.actions_bar_layout)
        # WINDOW
        self.setLayout(self.main_layout)
        # Use GUIInfo to set the window size and position from settings
        self.setGeometry(*GUIInfo().get_window_geometry())

        self._do_clear_runner()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closing_signal.emit()
        self._do_kill_process()
        event.accept()
        self.destroy()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def _do_clear_runner(self) -> None:
        self.text.clear()

    def _do_kill_process(self) -> None:
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            # Terminate the main process and its child processes
            parent_process = psutil.Process(self.process.processId())
            children = parent_process.children(recursive=True)
            for child in children:
                child.terminate()
            parent_process.terminate()
            self.process.waitForFinished()
            self.process_killed = True

    def _do_restart_process(self) -> None:
        if self.process_last_command != "":
            self.message("\nRestarting last used process...\n")
            self.execute(self.process_last_command, self.process_last_args)

    def _do_save_runner_output(self) -> None:
        """
        Export the current list of active mods to a user-designated
        file. The current list does not need to have been saved.
        """
        if self.text != "":
            logger.info("Opening file dialog to specify output file")
            file_path = show_dialogue_file(
                mode="save",
                caption="Save runner output",
                _dir=os.path.expanduser("~"),
                _filter="text files (*.txt)",
            )
            logger.info(f"Selected path: {file_path}")
            if file_path:
                logger.info(
                    "Exporting current runner output to the designated txt file"
                )
                with open(file_path, "w", encoding="utf-8") as outfile:
                    logger.info("Writing to file")
                    outfile.write(self.text.toPlainText())

    def change_progress_bar_color(self, state: str) -> None:
        self.progress_bar.setObjectName(state)
        self.progress_bar.style().unpolish(self.progress_bar)
        self.progress_bar.style().polish(self.progress_bar)

    # TODO: Additional isn't used. Remove it?
    def execute(
        self,
        command: str,
        args: Sequence[str],
        progress_bar: int | None = None,
        additional: None = None,
    ) -> None:
        """
        Execute the given command in a new terminal like gui

        command:str, path to .exe
        args:list, argument for .exe
        progress_bar:Optional int, value for the progress bar, -1 to not set value
        additional:Optional, data to parse to the runner
        """
        logger.info("RunnerPanel subprocess initiating...")
        self.restart_process_button.show()
        self.kill_process_button.show()
        self.process_last_command = command
        self.process_last_args = args
        self.process = QProcess(self)
        self.process.setProgram(command)
        self.process.setArguments(args)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardError.connect(self.handle_output)
        self.process.readyReadStandardOutput.connect(self.handle_output)
        self.process.finished.connect(self.finished)
        if progress_bar:
            self.progress_bar.show()
            self.progress_bar.setValue(0)
            if progress_bar > 0:
                if "steamcmd" in command:
                    self.progress_bar.setRange(0, progress_bar)
                    self.progress_bar.setFormat("%v/%m")
        if not self.todds_dry_run_support:
            self.message(f"\nExecuting command:\n{command} {' '.join(args)}\n\n")
        self.process.start()

    def handle_output(self) -> None:
        data = self.process.readAll()
        stdout = self.ansi_escape.sub("", bytes(data.data()).decode("utf8"))
        self.message(stdout)

    def message(self, line: str) -> None:
        overwrite = False
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            logger.debug(f"[{self.process.program().split('/')[-1]}]\n{line}")
        else:
            logger.debug(f"{line}")

        # Hardcoded steamcmd progress output support
        if (  # -------STEAM-------
            self.process
            and self.process.state() == QProcess.ProcessState.Running
            and "steamcmd" in self.process.program()
        ):
            if "Downloading item " in line:
                match = search(r"Downloading item (\d+)...", line)
                if match:
                    self.steamcmd_current_pfid = match.group(1)
            # Overwrite when SteamCMD client is doing updates
            if (
                ("] Downloading update (" in line)
                or ("] Installing update" in line)
                or ("] Extracting package" in line)
            ):
                overwrite = True
            # Properly format lines
            if "workshop_download_item" in line:
                line = line.replace(
                    "workshop_download_item", "\n\nworkshop_download_item"
                )
            elif ") quit" in line:
                line = line.replace(") quit", ")\n\nquit")
            # Progress bar output support
            success_matches = findall(
                r"Success. Downloaded item (\d+)", line
            )  # Handle all success messages in the line
            if success_matches:
                for success_pfid in success_matches:
                    if success_pfid in self.steamcmd_download_tracking:
                        self.steamcmd_download_tracking.remove(success_pfid)
                        self.progress_bar.setValue(self.progress_bar.value() + 1)
            elif "ERROR! Download item " in line:
                self.change_progress_bar_color("warn")
                self.progress_bar.setValue(self.progress_bar.value() + 1)
            elif "ERROR! Not logged on." in line:
                self.change_progress_bar_color("critical")
                self.progress_bar.setValue(self.progress_bar.value() + 1)
            # -------STEAM-------

        # Hardcoded todds progress output support
        elif (  # -------TODDS-------
            self.process
            and self.process.state() == QProcess.ProcessState.Running
            and "todds" in self.process.program()
        ):
            match = search(r"Progress: (\d+)/(\d+)", line)
            if match:
                self.progress_bar.setRange(0, int(match.group(2)))
                self.progress_bar.setValue(int(match.group(1)))
                overwrite = True
            # -------TODDS-------

        # Hardcoded query progress output support
        # -------QUERY-------
        match = search(
            r"IPublishedFileService/(QueryFiles|GetDetails) (page|chunk) \[(\d+)\/(\d+)\]",
            line,
        )
        if match:
            operation, pagination, start, end = match.groups()
            self.progress_bar.setRange(0, int(end))
            self.progress_bar.setValue(int(start))
            overwrite = True
        # -------QUERY-------

        # Overwrite support - set the overwrite bool to overwrite the last line instead of appending
        if overwrite:
            cursor = self.text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.movePosition(
                QTextCursor.MoveOperation.StartOfLine,
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.removeSelectedText()
            cursor.insertText(line.strip())
        else:
            self.text.appendPlainText(line)
        self.previous_line = line

    def finished(self) -> None:
        # Handle output filtering if todds dry run support is not enabled
        if not self.todds_dry_run_support:
            # Determine message based on whether the process was killed
            self.message(
                "Subprocess killed!" if self.process_killed else "Subprocess completed."
            )
            self.process_killed = False  # Reset the kill flag

            # Process-specific logic for steamcmd
            if "steamcmd" in self.process.program():
                # Only proceed if there are mods that did not successfully download
                if (
                    self.steamcmd_download_tracking
                    and len(self.steamcmd_download_tracking) > 0
                ):
                    self.change_progress_bar_color("emergency")
                    pfids_to_name = {}
                    failed_mods_no_names = []

                    # Attempt to resolve mod names from a local database
                    if self.steam_db:
                        for failed_mod_pfid in self.steamcmd_download_tracking:
                            mod_info = self.steam_db.get(failed_mod_pfid)
                            if mod_info:
                                mod_name = mod_info.get("steamName") or mod_info.get(
                                    "name"
                                )
                                if mod_name:
                                    pfids_to_name[failed_mod_pfid] = mod_name
                                else:
                                    failed_mods_no_names.append(failed_mod_pfid)

                    # Attempt to resolve remaining mod names via a WebAPI
                    if failed_mods_no_names:
                        mod_details_lookup = (
                            ISteamRemoteStorage_GetPublishedFileDetails(
                                failed_mods_no_names
                            )
                        )
                        if mod_details_lookup:
                            for mod_metadata in mod_details_lookup:
                                mod_title = mod_metadata.get("title")
                                if mod_title:
                                    pfids_to_name[mod_metadata["publishedfileid"]] = (
                                        mod_title
                                    )

                    # Compile details of failed mods for the report
                    details = "\n".join(
                        f"{pfids_to_name.get(pfid, '*Mod name not found!*')} - {pfid}"
                        for pfid in self.steamcmd_download_tracking
                    )

                    # Prompt user for action on failed mods
                    if (
                        show_dialogue_conditional(
                            title=self.tr("SteamCMD downloader"),
                            text=self.tr(
                                "SteamCMD failed to download mod(s)! Would you like to retry download of the mods that failed?\n\nClick 'Show Details' to see a list of mods that failed."
                            ),
                            details=details,
                        )
                        == "&Yes"
                    ):
                        self.steamcmd_downloader_signal.emit(
                            self.steamcmd_download_tracking
                        )
                    else:
                        logger.debug("User declined re-download of failed mods.")
                else:
                    self.change_progress_bar_color("success")

            # Process-specific logic for todds
            if "todds" in self.process.program():
                self.change_progress_bar_color("success")

        # Cleanup process
        self.process.terminate()
        self.process_complete()

    def process_complete(self) -> None:
        diag = BinaryChoiceDialog(
            title=self.tr("Process Complete"),
            text=self.tr("Process complete, you can close the window."),
            positive_text=self.tr("Close Window"),
            negative_text=self.tr("Ok"),
        )
        if diag.exec_is_positive():
            self.close()
