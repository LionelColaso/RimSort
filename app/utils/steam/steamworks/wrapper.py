import os
import shutil
import subprocess
import sys
from collections.abc import MutableMapping
from multiprocessing import Process
from os import getcwd
from pathlib import Path
from threading import Thread
from time import sleep, time
from typing import Any, Optional, Union

import psutil
from loguru import logger

from app.utils.generic import (
    launch_game_process,
    show_no_steam_warning,
    show_snap_steam_warning,
)

# If we're running from a Python interpreter, makesure steamworks module is in our sys.path ($PYTHONPATH)
# Ensure that this is available by running `git submodule update --init --recursive`
# You can automatically ensure this is done by utilizing distribute.py
if "__compiled__" not in globals():
    sys.path.append(str((Path(getcwd()) / "submodules" / "SteamworksPy")))

from steamworks import STEAMWORKS  # type: ignore

SLEEP_TIME = 15
MAX_ATTEMPTS = 10


def _find_steam_executable() -> Optional[Path]:
    """
    Find the Steam executable path based on the current platform.

    Returns:
        Optional[Path]: Path to Steam executable, or None if not found
    """
    if sys.platform == "win32":
        from app.utils.win_find_steam import find_steam_folder

        if find_steam_folder is None:
            return None
        steam_path, found = find_steam_folder()
        if not found:
            return None
        return Path(steam_path) / "steam.exe"
    elif sys.platform == "darwin":
        return Path("/Applications/Steam.app/Contents/MacOS/steam_osx")
    elif sys.platform.startswith("linux"):
        # For Linux, we are directly launching using the 'steam' command
        return None
    else:
        return None


def _is_steam_running() -> bool:
    """
    Check if Steam is currently running by looking for Steam processes.

    Returns:
        bool: True if Steam is running, False otherwise
    """
    if psutil is None:
        return False
    try:
        steam_processes: list[str] = []
        # Retry up to 5 times with 2 second delay to account for process startup time
        for attempt in range(5):
            steam_processes = []
            for process in psutil.process_iter(attrs=["name", "exe"]):
                try:
                    name = process.info["name"]
                    exe = process.info["exe"]
                    if name and "steam" in name.lower():
                        steam_processes.append(name)
                    # Also check executable path for steam
                    if exe and "steam" in exe.lower():
                        steam_processes.append(f"{name} ({exe})")
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    continue

            # Check for main Steam processes based on platform
            if sys.platform == "win32":
                steam_indicators = [
                    "steam.exe",
                    "steamwebhelper.exe",
                    "steamservice.exe",
                    "steamerrorreporter.exe",
                    "steamerrorreporter64.exe",
                ]
            elif sys.platform == "darwin":
                steam_indicators = [
                    "steam_osx",
                    "steamwebhelper",
                ]
            elif sys.platform.startswith("linux"):
                steam_indicators = [
                    "steam",
                    "steamwebhelper",
                ]
            else:
                steam_indicators = [
                    "steam",
                    "steamwebhelper",
                ]

            for process in psutil.process_iter(attrs=["name"]):
                try:
                    name = process.info["name"]
                    if name.lower() in steam_indicators:
                        logger.debug(f"Found Steam process: {name}")
                        return True
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    continue

            if attempt < 4:  # Don't sleep on the last attempt
                sleep(2)

        logger.debug(f"Steam processes found: {steam_processes}")
        return False
    except Exception as e:
        logger.warning(f"Error checking if Steam is running: {e}")
        return False


def _setup_snap_steam_env(env: MutableMapping[str, str]) -> None:
    """
    Configure environment variables for snap Steam compatibility.

    Args:
        env: Environment dictionary to update
    """
    snap_steam_path = (
        Path.home() / "snap" / "steam" / "common" / ".local" / "share" / "Steam"
    )
    if snap_steam_path.exists():
        logger.debug("Configuring environment for snap Steam...")
        env["STEAM_COMPAT_TOOL_PATHS"] = str(snap_steam_path)
        env["STEAMRUNTIME_PATH"] = str(snap_steam_path / "ubuntu12_32")


def _launch_steam(_libs: str) -> bool:
    """
    Launch Steam if it's not running and wait for it to start.

    Args:
        _libs: Path to the Steamworks library directory

    Returns:
        bool: True if Steam was launched successfully, False otherwise
    """
    try:
        steam_exe = _find_steam_executable()
        if steam_exe is None:
            if not sys.platform.startswith("linux"):
                logger.warning("Steam executable not found")
                return False

            # For Linux, try to launch steam in a terminal emulator
            logger.info("Launching Steam via 'steam' command in a terminal...")
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = _libs + os.pathsep + env.get("LD_LIBRARY_PATH", "")

            # Configure snap Steam environment if available
            _setup_snap_steam_env(env)

            terminal_candidates = [
                "gnome-terminal",
                "konsole",
                "xfce4-terminal",
                "mate-terminal",
                "xterm",
                "x-terminal-emulator",
            ]
            terminal = next((t for t in terminal_candidates if shutil.which(t)), None)

            try:
                if terminal:
                    logger.debug(f"Using terminal emulator: {terminal}")
                    if terminal == "gnome-terminal":
                        subprocess.Popen([terminal, "--", "steam"], env=env)
                    else:
                        subprocess.Popen([terminal, "-e", "steam"], env=env)
                else:
                    logger.warning(
                        "No terminal emulator found, falling back to direct launch"
                    )
                    subprocess.Popen(["steam"], env=env)
            except FileNotFoundError:
                logger.warning("Steam executable or terminal emulator not found")
                return False
        else:
            if not steam_exe.exists():
                logger.warning("Steam executable not found")
                return False
            logger.info("Launching Steam...")
            env = os.environ.copy()
            # Configure snap Steam environment if available (for cross-platform compatibility)
            _setup_snap_steam_env(env)
            subprocess.Popen([str(steam_exe)], env=env)
        # Give Steam some initial time to start up before checking
        sleep(SLEEP_TIME)

        # First check if Steam processes are running after initial launch
        if _is_steam_running():
            logger.info("Steam processes detected after launch")
            # Give Steam a bit more time to fully initialize
            sleep(SLEEP_TIME)
            return True

        # Wait for Steam to start checks every SLEEP_TIME (15 seconds), MAX_ATTEMPTS (10 attempts).
        for attempt in range(MAX_ATTEMPTS):
            sleep(SLEEP_TIME)
            # Check both process detection and API initialization
            if _is_steam_running():
                logger.info("Steam processes detected during API wait")
                # Give Steam a bit more time to fully initialize
                sleep(SLEEP_TIME)
                return True
            try:
                # Try to create a temporary Steamworks instance to test if Steam is ready
                test_steamworks = STEAMWORKS()
                test_steamworks.initialize()
                test_steamworks.unload()
                logger.info("Steam launched and API initialized successfully")
                # Give Steam a bit more time to fully initialize
                sleep(SLEEP_TIME)
                return True
            except Exception as e:
                error_msg = f"{e.__class__.__name__}: {e}"
                logger.debug(
                    f"Steam API not ready yet (attempt {attempt + 1}/{MAX_ATTEMPTS}): {error_msg}"
                )
                # Log more details on the last attempt
                if attempt == MAX_ATTEMPTS - 1:
                    total_time = SLEEP_TIME + (MAX_ATTEMPTS * SLEEP_TIME)
                    logger.warning(
                        f"Steamworks initialization failed after {total_time} seconds: {error_msg}"
                    )
                    if "snap" in str(Path.home()):
                        logger.warning(
                            "Snap Steam detected - ensure you have a native Steam installation for Steamworks support"
                        )
                continue

        logger.warning("Steam failed to start within timeout")
        return False

    except Exception as e:
        logger.warning(f"Error launching Steam: {e}")
        return False


def check_steam_available(_libs: str) -> bool:
    """
    Check if Steam is available and running.

    Checks if Steam is running, and if not, attempts to launch it.
    Also checks for snap Steam incompatibility.

    Args:
        _libs: Path to the Steamworks library directory

    Returns:
        bool: True if Steam is available, False otherwise
    """
    # Check for snap Steam (incompatible with Steamworks)
    snap_steam_path = (
        Path.home() / "snap" / "steam" / "common" / ".local" / "share" / "Steam"
    )
    is_snap_steam = snap_steam_path.exists()

    if is_snap_steam and sys.platform.startswith("linux"):
        logger.warning(
            "Snap Steam detected. Snap Steam is incompatible with Steamworks due to sandboxing. "
            "Steam integration is unavailable."
        )
        # Show snap steam warning
        show_snap_steam_warning()
        return False

    # Check if Steam is running
    if not _is_steam_running():
        logger.info("Steam is not running, attempting to launch...")
        if not _launch_steam(_libs):
            logger.error("Failed to launch Steam")
            # Show no steam warning
            show_no_steam_warning()
            return False

    return True


class SteamworksInterface:
    """
    A class object to handle our interactions with SteamworksPy

    https://github.com/philippj/SteamworksPy
    https://philippj.github.io/SteamworksPy/
    https://github.com/philippj/SteamworksPy/issues/62
    https://github.com/philippj/SteamworksPy/issues/75
    https://github.com/philippj/SteamworksPy/pull/76

    Thanks to Paladin for the example
    """

    def __init__(
        self,
        callbacks: bool,
        callbacks_total: int | None = None,
        _libs: str | None = None,
    ) -> None:
        logger.info("SteamworksInterface initializing...")
        self.callbacks = callbacks
        self.callbacks_count = 0
        self.callbacks_total = callbacks_total
        if self.callbacks:
            logger.debug("Callbacks enabled!")
            self.end_callbacks = False  # Signal used to end the _callbacks Thread
            if (
                self.callbacks_total
            ):  # Pass this if you want to do multiple actions with 1 initialization
                logger.debug(f"Callbacks total : {self.callbacks_total}")
                self.multiple_queries = True
            else:
                self.multiple_queries = False
        # Used for GetAppDependencies data
        self.get_app_deps_query_result: dict[int, Any] = {}
        self.steam_not_running = False  # Skip action if True. Log occurrences.
        self.steamworks = STEAMWORKS(_libs=_libs)
        try:
            self.steamworks.initialize()  # Init the Steamworks API
        except Exception as e:
            logger.warning(
                f"Unable to initialize Steamworks API due to exception: {e.__class__.__name__}"
            )
            logger.warning(
                "If you are a Steam user, please check that Steam running and that you are logged in..."
            )
            self.steam_not_running = True
        if not self.steam_not_running:  # Skip if True
            if self.callbacks:
                # Start the thread
                logger.debug("Starting thread")
                self.steamworks_thread = self._daemon()
                self.steamworks_thread.start()

    def _callbacks(self) -> None:
        logger.debug("Starting _callbacks")
        while (
            not self.steamworks.loaded()
        ):  # This should not execute as long as Steamworks API init went OK
            logger.warning("Waiting for Steamworks...")
        else:
            logger.info("Steamworks loaded!")
        while not self.end_callbacks:
            self.steamworks.run_callbacks()
            sleep(0.1)
        else:
            logger.info(
                f"{self.callbacks_count} callback(s) received. Ending thread..."
            )

    # TODO: Rework this for proper static type checking
    def _cb_app_dependencies_result_callback(self, *args: Any, **kwargs: Any) -> None:
        """
        Executes upon Steamworks API callback response
        """
        # Add to callbacks count
        self.callbacks_count = self.callbacks_count + 1
        # Debug prints
        logger.debug(f"GetAppDependencies query callback: {args}, {kwargs}")
        logger.debug(f"result : {args[0].result}")
        pfid = args[0].publishedFileId
        logger.debug(f"publishedFileId : {pfid}")
        app_dependencies_list = args[0].get_app_dependencies_list()
        logger.debug(f"app_dependencies_list : {app_dependencies_list}")
        # Collect data for our query if dependencies were returned
        if len(app_dependencies_list) > 0:
            self.get_app_deps_query_result[pfid] = app_dependencies_list
        # Check for multiple actions
        if self.multiple_queries and self.callbacks_count == self.callbacks_total:
            # Set flag so that _callbacks cease
            self.end_callbacks = True
        elif not self.multiple_queries:
            # Set flag so that _callbacks cease
            self.end_callbacks = True

    def _cb_subscription_action(self, *args: Any, **kwargs: Any) -> None:
        """
        Executes upon Steamworks API callback response
        """
        # Add to callbacks count
        self.callbacks_count = self.callbacks_count + 1
        # Debug prints
        logger.debug(f"Subscription action callback: {args}, {kwargs}")
        logger.debug(f"result: {args[0].result}")
        logger.debug(f"PublishedFileId: {args[0].publishedFileId}")
        # Uncomment to see steam client install info of the mod
        # logger.info(
        #     self.steamworks.Workshop.GetItemInstallInfo(args[0].publishedFileId)
        # )
        # Check for multiple actions
        if self.multiple_queries and self.callbacks_count == self.callbacks_total:
            # Set flag so that _callbacks cease
            self.end_callbacks = True
        elif not self.multiple_queries:
            # Set flag so that _callbacks cease
            self.end_callbacks = True

    def _daemon(self) -> Thread:
        """
        Returns a Thread pointing to our _callbacks daemon
        """
        return Thread(target=self._callbacks, daemon=True)

    def _wait_for_callbacks(self, timeout: int) -> None:
        """
        Waits for the Steamworks API callbacks to complete within a specified time interval.

        Args:
            timeout (int): Maximum time to wait in seconds.

        Returns:
            None
        """
        start_time = time()
        logger.debug(f"Waiting {timeout} seconds for Steamworks API callbacks...")
        while self.steamworks_thread.is_alive():
            elapsed_time = time() - start_time
            if elapsed_time >= timeout:
                self.end_callbacks = True
                break
            sleep(1)


class SteamworksAppDependenciesQuery:
    def __init__(
        self,
        pfid_or_pfids: Union[int, list[int]],
        interval: int = 1,
        _libs: str | None = None,
    ) -> None:
        self._libs = _libs
        self.interval = interval
        self.pfid_or_pfids = pfid_or_pfids

    def run(self) -> None | dict[int, Any]:
        """
        Query PublishedFileIDs for AppID dependency data
        :param pfid_or_pfids: is an int that corresponds with a subscribed Steam mod's PublishedFileId
                            OR is a list of int that corresponds with multiple Steam mod PublishedFileIds
        :param interval: time in seconds to sleep between multiple subsequent API calls
        """
        logger.info(
            f"Creating SteamworksInterface and passing PublishedFileID(s) {self.pfid_or_pfids}"
        )
        # If the chunk passed is a single int, convert it into a list in an effort to simplify procedure
        if isinstance(self.pfid_or_pfids, int):
            self.pfid_or_pfids = [self.pfid_or_pfids]
        # Create our Steamworks interface and initialize Steamworks API
        steamworks_interface = SteamworksInterface(
            callbacks=True, callbacks_total=len(self.pfid_or_pfids), _libs=self._libs
        )
        if not steamworks_interface.steam_not_running:  # Skip if True
            while not steamworks_interface.steamworks.loaded():  # Ensure that Steamworks API is initialized before attempting any instruction
                break
            else:
                for pfid in self.pfid_or_pfids:
                    logger.debug(f"ISteamUGC/GetAppDependencies Query: {pfid}")
                    steamworks_interface.steamworks.Workshop.SetGetAppDependenciesResultCallback(
                        steamworks_interface._cb_app_dependencies_result_callback
                    )
                    steamworks_interface.steamworks.Workshop.GetAppDependencies(pfid)
                    # Sleep for the interval if we have more than one pfid to action on
                    if len(self.pfid_or_pfids) > 1:
                        sleep(self.interval)
                # Patience, but don't wait forever
                steamworks_interface._wait_for_callbacks(timeout=60)
                # This means that the callbacks thread has ended. We are done with Steamworks API now, so we dispose of everything.
                logger.info("Thread completed. Unloading Steamworks...")
                steamworks_interface.steamworks_thread.join()
                # Grab the data and return it
                logger.warning(
                    f"Returning {len(steamworks_interface.get_app_deps_query_result.keys())} results..."
                )
                return steamworks_interface.get_app_deps_query_result
        else:
            steamworks_interface.steamworks.unload()

        return None


class SteamworksGameLaunch(Process):
    def __init__(
        self, game_install_path: str, args: list[str], _libs: str | None = None
    ) -> None:
        Process.__init__(self)
        self._libs = _libs
        self.game_install_path = game_install_path
        self.args = args

    def run(self) -> None:
        """
        Handle SW game launch; instructions received from connected signals

        :param game_install_path: is a string path to the game folder
        :param args: is a string representing the args to pass to the generated executable path
        """
        logger.info("Creating SteamworksInterface and launching game executable")
        # Try to initialize the SteamWorks API, but allow game to launch if Steam not found
        steamworks_interface = SteamworksInterface(callbacks=False, _libs=self._libs)

        # Launch the game
        launch_game_process(
            game_install_path=Path(self.game_install_path), args=self.args
        )
        # If we had an API initialization, try to unload it
        if (
            not steamworks_interface.steam_not_running
            and steamworks_interface.steamworks
        ):
            # Unload Steamworks API
            steamworks_interface.steamworks.unload()


class SteamworksSubscriptionHandler:
    def __init__(
        self,
        action: str,
        pfid_or_pfids: Union[int, list[int]],
        interval: int = 1,
        _libs: str | None = None,
    ):
        # Optionally set _libs path for Steamworks
        self._libs = _libs
        self.action = action
        self.pfid_or_pfids = pfid_or_pfids
        self.interval = interval

    def run(self) -> None:
        """
        Handle Steam mod subscription actions received from connected signals

        :param action: is a string that corresponds with the following supported_actions[]
        :param pfid_or_pfids: is an int that corresponds with a subscribed Steam mod's PublishedFileId
                            OR is a list of int that corresponds with multiple Steam mod PublishedFileIds
        :param interval: time in seconds to sleep between multiple subsequent API calls
        """

        logger.info(
            f"Creating SteamworksInterface and passing instruction {self.action}"
        )
        # If the chunk passed is a single int, convert it into a list in an effort to simplify procedure
        if isinstance(self.pfid_or_pfids, int):
            self.pfid_or_pfids = [self.pfid_or_pfids]
        # Create our Steamworks interface and initialize Steamworks API
        # If we are resubscribing, it's actually 2 callbacks to expect per pfid, because it is 2 API calls
        if self.action == "resubscribe":
            callbacks_total = len(self.pfid_or_pfids) * 2  # per API call
        # Otherwise we only expect a single callback for each API call
        else:
            callbacks_total = len(self.pfid_or_pfids)
        steamworks_interface = SteamworksInterface(
            callbacks=True, callbacks_total=callbacks_total, _libs=self._libs
        )
        if not steamworks_interface.steam_not_running:  # Skip if True
            while not steamworks_interface.steamworks.loaded():  # Ensure that Steamworks API is initialized before attempting any instruction
                break
            else:
                if self.action == "resubscribe":
                    for pfid in self.pfid_or_pfids:
                        logger.debug(
                            f"ISteamUGC/UnsubscribeItem + SubscribeItem Action : {pfid}"
                        )
                        # Point Steamworks API callback response to our functions
                        steamworks_interface.steamworks.Workshop.SetItemUnsubscribedCallback(
                            steamworks_interface._cb_subscription_action
                        )
                        steamworks_interface.steamworks.Workshop.SetItemSubscribedCallback(
                            steamworks_interface._cb_subscription_action
                        )
                        # Create API calls
                        steamworks_interface.steamworks.Workshop.UnsubscribeItem(pfid)
                        sleep(self.interval)
                        steamworks_interface.steamworks.Workshop.SubscribeItem(pfid)
                        # Sleep for the interval if we have more than one pfid to action on
                        if len(self.pfid_or_pfids) > 1:
                            sleep(self.interval)
                elif self.action == "subscribe":
                    for pfid in self.pfid_or_pfids:
                        logger.debug(f"ISteamUGC/SubscribeItem Action : {pfid}")
                        # Point Steamworks API callback response to our functions
                        steamworks_interface.steamworks.Workshop.SetItemSubscribedCallback(
                            steamworks_interface._cb_subscription_action
                        )
                        # Create API calls
                        steamworks_interface.steamworks.Workshop.SubscribeItem(pfid)
                        # Sleep for the interval if we have more than one pfid to action on
                        if len(self.pfid_or_pfids) > 1:
                            sleep(self.interval)
                elif self.action == "unsubscribe":
                    for pfid in self.pfid_or_pfids:
                        logger.debug(f"ISteamUGC/UnsubscribeItem Action : {pfid}")
                        # Point Steamworks API callback response to our functions
                        steamworks_interface.steamworks.Workshop.SetItemUnsubscribedCallback(
                            steamworks_interface._cb_subscription_action
                        )
                        # Create API calls
                        steamworks_interface.steamworks.Workshop.UnsubscribeItem(pfid)
                        # Sleep for the interval if we have more than one pfid to action on
                        if len(self.pfid_or_pfids) > 1:
                            sleep(self.interval)
                # Patience, but don't wait forever
                steamworks_interface._wait_for_callbacks(timeout=10)
                # This means that the callbacks thread has ended. We are done with Steamworks API now, so we dispose of everything.
                logger.info("Thread completed. Unloading Steamworks...")
                steamworks_interface.steamworks_thread.join()
                # Unload Steamworks API
                steamworks_interface.steamworks.unload()
        else:
            steamworks_interface.steamworks.unload()


if __name__ == "__main__":
    sys.exit()
