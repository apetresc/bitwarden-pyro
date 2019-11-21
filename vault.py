#!/usr/bin/env python

from subprocess import CalledProcessError
from logger import BwLogger
import subprocess as sp
import json


class Vault:
    def __init__(self):
        self.items = None

        self._logger = BwLogger().get_logger()

    def load_items(self, key):
        try:
            self._logger.info("Loading items from bw")
            load_cmd = f"bw list items --session {key}"

            proc = sp.run(load_cmd.split(), capture_output=True, check=True)
            items_json = proc.stdout.decode("utf-8")
            self.items = json.loads(items_json)

            return len(self.items)
        except CalledProcessError:
            self._logger.error("Failed to load vault items")
            return 0


class VaultException(Exception):
    """Base class for items generated by Vault"""
    pass


class LoadException(VaultException):
    """Raised when vault fails to load items"""
    pass
