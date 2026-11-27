import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from browser.web_media_storage import bind_inputs
from cards.web_card_inputs import prepare, digest


class MediaStorageTests(unittest.TestCase):
    def test_absent_volume_creates_no_ssd_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'local';folder.mkdir()
            with patch.object(Path,'is_mount',return_value=False):
                with self.assertRaises(OSError):bind_inputs(folder,'paper',root/'ssd/media',root/'ssd')
            self.assertFalse((root/'ssd/media').exists())

    def test_prepare_payload_on_ssd_receipts_local(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'local';media=root/'ssd/media'
            doc=pymupdf.open();doc.new_page().insert_text((50,50),'test source');doc.save(root/'original.pdf');doc.close()
            with patch.object(Path,'is_mount',return_value=True):
                packet=prepare(root/'original.pdf',folder,'paper','test',digest(root/'original.pdf'),media,root/'ssd')
            for name in ('source.pdf','visual.pdf','pages'):
                self.assertTrue((folder/name).is_symlink())
                self.assertTrue((media/'paper'/name).exists())
            self.assertFalse((folder/'packet.json').is_symlink())
            self.assertFalse((folder/'source-context.json').is_symlink())
            for name,h in packet['input_hashes'].items():self.assertEqual(digest(folder/name),h)

    def test_outside_volume_rejected(self):
        with patch.object(Path,'is_mount',return_value=True):
            with self.assertRaises(ValueError):bind_inputs('/tmp/local','paper','/tmp/elsewhere','/Volumes/ssd')


if __name__=='__main__':unittest.main()
