from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from image_tool import download, validate_lock


LOCK = json.loads(Path(sys.argv.pop()).read_text())


class ImageLockTest(unittest.TestCase):
    def test_download_retries_transport_failure_then_checks_hash(self):
        package = dict(LOCK["packages"][0], sha256=hashlib.sha256(b"valid").hexdigest())
        with tempfile.TemporaryDirectory() as directory, mock.patch("urllib.request.urlopen") as response, mock.patch("time.sleep"):
            stream = mock.MagicMock()
            stream.__enter__.return_value.read.return_value = b"valid"
            response.side_effect = [ConnectionResetError(), stream]
            self.assertEqual(download(package, Path(directory)).read_bytes(), b"valid")
            self.assertEqual(response.call_count, 2)

    def test_complete_lock_is_pinned(self):
        validate_lock(LOCK)
        self.assertGreater(len(LOCK["packages"]), 1)

    def test_rejects_unpinned_or_escaping_inputs(self):
        for field, value in [("filename", "../escape.deb"), ("url", "http://example.org/pkg.deb"), ("sha256", "bad")]:
            lock = copy.deepcopy(LOCK)
            lock["packages"][0][field] = value
            with self.assertRaises(ValueError):
                validate_lock(lock)

    def test_download_rejects_corrupt_data(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch("urllib.request.urlopen") as response:
            response.return_value.__enter__.return_value.read.return_value = b"corrupt"
            with self.assertRaises(ValueError):
                download(LOCK["packages"][0], Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
