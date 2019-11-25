from bitwarden_pyro.util.logger import ProjectLogger
from bitwarden_pyro.util.arguments import parse_arguments
from bitwarden_pyro.settings import NAME, VERSION
from bitwarden_pyro.view.rofi import Rofi
from bitwarden_pyro.controller.session import Session, SessionException
from bitwarden_pyro.controller.autotype import AutoType, AutoTypeException
from bitwarden_pyro.controller.clipboard import Clipboard, ClipboardException
from bitwarden_pyro.controller.vault import Vault, VaultException
from bitwarden_pyro.model.actions import ItemActions, WindowActions
from bitwarden_pyro.util.formatter import ItemFormatter, ConverterFactory

from enum import Enum, auto
from time import sleep
import re


class BwPyro:
    def __init__(self):
        self._rofi = None
        self._session = None
        self._vault = None
        self._clipboard = None
        self._autotype = None
        self._args = parse_arguments()
        self._logger = ProjectLogger(self._args.verbose).get_logger()

    def start(self):
        if self._args.version:
            print(f"{NAME} v{VERSION}")
            exit()
        elif self._args.lock:
            self.__lock()
        else:
            self.__launch_ui()

    def __lock(self):
        try:
            self._logger.info("Locking vault and deleting session")
            self._session = Session()
            self._session.lock()
        except SessionException:
            pass

    def __unlock(self, force=False):
        self._logger.info("Unlocking bitwarden vault")
        if not self._session.has_key() or force:
            pwd = self._rofi.get_password()
            if pwd is not None:
                self._session.unlock(pwd)
            else:
                self._logger.info("Unlocking aborted")
                exit(0)

        k = self._session.get_key()
        self._vault.set_key(k)

    def __show_items(self):
        items = self._vault.get_items()
        # Convert items to \n separated strings
        formatted = ItemFormatter.unique_format(items)
        selected_name, event = self._rofi.show_items(formatted)
        self._logger.debug("User selected login: %s", selected_name)

        # Rofi dialog has been closed
        if selected_name is None:
            self._logger.debug("Item selection has been aborted")
            return (None, None)
        # Make sure that the group item isn't a single item where
        # the deduplication marker coincides
        elif selected_name.startswith(ItemFormatter.DEDUP_MARKER) and \
                len(self._vault.get_by_name(selected_name)) == 0:
            self._logger.debug("User selected item group")
            group_name = selected_name[len(ItemFormatter.DEDUP_MARKER):]
            selected_items = self._vault.get_by_name(group_name)
            return (WindowActions.SHOW_GROUP, selected_items)
        # A single item has been selected
        else:
            self._logger.debug("User selected single item")
            selected_item = self._vault.get_by_name(selected_name)
            return (event, selected_item)

    def __show_group_items(self, items=None, fields=None, ignore=None):
        if items is None:
            items = self._vault.get_items()

        name = items[0]['name']
        converter = ConverterFactory.create(fields, ignore)
        indexed, formatted = ItemFormatter.group_format(items, converter)
        selected_name, event = self._rofi.show_items(formatted, name)

        # Rofi has been closed
        if selected_name is None:
            self._logger.debug("Group item selection has been aborted")
            return (None, None)
        # An item has been selected
        else:
            regex = r"^#([0-9]+): .*"
            match = re.search(regex, selected_name)
            selected_index = int(match.group(1)) - 1
            selected_item = indexed[selected_index]
            return (event, selected_item)

    def __load_items(self):
        try:
            # First attempt at loading items
            count = self._vault.load_items()

            # Second attempt, as key might get invalidated by running bw manually
            if count == 0:
                self._logger.warning(
                    "First attempt at loading vault items failed")
                self.__unlock(force=True)
                count = self._vault.load_items()

            # Last attempt failed, abort execution
            if count == 0:
                self._logger.error(
                    "Aborting execution, as second attempt at " +
                    "loading vault items failed"
                )
                exit(0)
        except SessionException:
            self._logger.error("Failed to load items")

    def __launch_ui(self):
        self._logger.info("Application has been launched")
        try:
            self._session = Session(self._args.timeout)
            self._rofi = Rofi(self._args.rofi_args, self._args.enter)
            self._clipboard = Clipboard(self._args.clear)
            self._autotype = AutoType()
            self._vault = Vault()

            self._enter_action = self._args.enter
            self._rofi.add_keybind('Alt+1', ItemActions.PASSWORD)
            self._rofi.add_keybind('Alt+2', ItemActions.ALL)
            self._rofi.add_keybind('Alt+t', ItemActions.TOTP)
            self._rofi.add_keybind('Alt+r', WindowActions.SYNC)
            self._rofi.add_keybind('Alt+u', WindowActions.SHOW_URI)
            self._rofi.add_keybind('Alt+n', WindowActions.SHOW_NAMES)
            self._rofi.add_keybind('Alt+l', WindowActions.SHOW_LOGIN)
        except (ClipboardException, AutoTypeException,
                SessionException, VaultException):
            self._logger.exception(f"Failed to initialise application")
            exit(1)

        try:

            self.__unlock()
            self.__load_items()

            action = WindowActions.SHOW_NAMES
            while action is not None and isinstance(action, WindowActions):
                self._logger.info("Switch window mode to %s", action)
                # A group of items has been selected
                if action == WindowActions.SHOW_NAMES:
                    action, item = self.__show_items()
                elif action == WindowActions.SHOW_GROUP:
                    action, item = self.__show_group_items(
                        items=item,
                        fields=['login.username']
                    )
                elif action == WindowActions.SHOW_URI:
                    action, item = self.__show_group_items(
                        fields=['login.uris.uri'],
                        ignore=['http://', 'https://', 'None']
                    )

                elif action == WindowActions.SHOW_LOGIN:
                    action, item = self.__show_group_items(
                        fields=['name', 'login.username']
                    )
                elif action == WindowActions.SYNC:
                    self._logger.info("Received SYNC command")
                    self._vault.sync()
                    self.__load_items()
                    action, item = self.__show_items()

            # Selection has been aborted
            if action == None:
                self._logger.info("Exiting. Login selection has been aborted")
                exit(0)

            if action == ItemActions.COPY:
                self._logger.info("Copying password to clipboard")
                self._clipboard.set(item['login']['password'])
            elif action == ItemActions.ALL:
                self._logger.info("Auto tying username and password")
                # Input delay allowing correct window to be focused
                sleep(1)
                self._autotype.string(item['login']['username'])
                sleep(0.2)
                self._autotype.key('Tab')
                sleep(0.2)
                self._autotype.string(item['login']['password'])
            elif action == ItemActions.PASSWORD:
                # Input delay allowing correct window to be focused
                sleep(1)
                self._logger.info("Auto typing password")
                self._autotype.string(item['login']['password'])
            elif action == ItemActions.TOTP:
                self._logger.info("Copying TOTP to clipboard")
                totp = self._vault.get_topt(item['id'])
                if totp is not None:
                    self._clipboard.set(totp)
                else:
                    self._logger.warning(
                        "Selected item does not provide a TOTP"
                    )
            else:
                self._logger.error("Unknown action received: %s", action)
        except (AutoTypeException, ClipboardException,
                SessionException, VaultException):
            self._logger.error("Application has received a critical error")


def run():
    bw_pyro = BwPyro()
    bw_pyro.start()
