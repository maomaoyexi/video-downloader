"""Portable dependency installation must verify hashes before creating a runtime."""
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.install_live_dependencies import install


class LiveDependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'dependency').mkdir()
        (self.root/'resource/dependencies').mkdir(parents=True)

    def fixture(self, filename='package/__init__.py', *, url='https://files.pythonhosted.org/package.whl', digest=None):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            archive.writestr(filename,'value=1')
        data = buffer.getvalue()
        lock = {'packages':[{'name':'package','version':'1','url':url,'sha256':digest or hashlib.sha256(data).hexdigest()}]}
        (self.root/'resource/dependencies/live-python.lock.json').write_text(json.dumps(lock),encoding='utf-8')
        return data

    def test_verified_wheel_install_is_idempotent_and_preserves_source_metadata(self):
        data=self.fixture()
        with patch('scripts.install_live_dependencies.urlopen',return_value=io.BytesIO(data)) as download:
            target=install(self.root)
            self.assertTrue((target/'package/__init__.py').is_file())
            self.assertEqual(install(self.root),target)
        self.assertEqual(download.call_count,1)

    def test_checksum_mismatch_never_creates_runtime(self):
        data=self.fixture(digest='0'*64)
        with patch('scripts.install_live_dependencies.urlopen',return_value=io.BytesIO(data)):
            with self.assertRaisesRegex(ValueError,'checksum'):
                install(self.root)
        self.assertFalse((self.root/'dependency/live-python').exists())
        self.assertEqual(len(list((self.root/'dependency').iterdir())),0)

    def test_upgrade_repairs_missing_files_even_when_the_lock_matches(self):
        data = self.fixture()
        with patch('scripts.install_live_dependencies.urlopen', side_effect=lambda *args, **kwargs: io.BytesIO(data)):
            target = install(self.root)
            module = target / 'package/__init__.py'
            module.unlink()
            self.assertEqual(install(self.root, upgrade=True), target)
        self.assertEqual(module.read_text(encoding='utf-8'), 'value=1')

    def test_zip_traversal_and_unofficial_hosts_are_rejected(self):
        data=self.fixture('../outside.py')
        with patch('scripts.install_live_dependencies.urlopen',return_value=io.BytesIO(data)):
            with self.assertRaisesRegex(ValueError,'path'):
                install(self.root)
        self.assertFalse((self.root/'dependency/outside.py').exists())
        self.fixture(url='https://evil.example/package.whl')
        with patch('scripts.install_live_dependencies.urlopen') as download:
            with self.assertRaisesRegex(ValueError,'official'):
                install(self.root)
        download.assert_not_called()

    def test_existing_unrelated_installation_is_not_overwritten(self):
        self.fixture()
        target=self.root/'dependency/live-python'
        target.mkdir()
        (target/'installed.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'different contents'):
            install(self.root)

    def test_managed_upgrade_and_protocol_assets_are_verified(self):
        data=self.fixture()
        with patch('scripts.install_live_dependencies.urlopen',return_value=io.BytesIO(data)):
            target=install(self.root)
        lock=json.loads((self.root/'resource/dependencies/live-python.lock.json').read_text())
        payload=b'# generated definition\n'
        lock['assets']=[{'path':'ndgr_client/proto/payload.py','url':'https://raw.githubusercontent.com/owner/repo/commit/file.py','sha256':hashlib.sha256(payload).hexdigest()}]
        (self.root/'resource/dependencies/live-python.lock.json').write_text(json.dumps(lock),encoding='utf-8')
        with patch('scripts.install_live_dependencies.urlopen',side_effect=[io.BytesIO(data),io.BytesIO(payload)]):
            install(self.root,upgrade=True)
        self.assertEqual((target/'ndgr_client/proto/payload.py').read_bytes(),payload)
        self.assertTrue((target/'ndgr_client/__init__.py').exists())

    def test_failed_upgrade_preserves_previous_verified_runtime(self):
        data=self.fixture()
        with patch('scripts.install_live_dependencies.urlopen',return_value=io.BytesIO(data)):
            target=install(self.root)
        marker=(target/'installed.json').read_bytes()
        self.fixture(digest='0'*64)
        with patch('scripts.install_live_dependencies.urlopen',return_value=io.BytesIO(data)):
            with self.assertRaises(ValueError):install(self.root,upgrade=True)
        self.assertEqual((target/'installed.json').read_bytes(),marker)


if __name__=='__main__':
    unittest.main()
