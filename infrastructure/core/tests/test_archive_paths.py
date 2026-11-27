import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.api import archive_paths__move_with_links as move


class ArchiveLinks(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.source=self.root/'chatgpt';self.source.mkdir()
        self.target=self.root/'ssd'/'evidence.txt';self.target.parent.mkdir();self.target.write_bytes(b'immutable evidence')
        (self.source/'relative.txt').symlink_to('../ssd/evidence.txt')
        (self.source/'absolute.txt').symlink_to(self.target)
        (self.source/'receipt.txt').write_bytes(b'original receipt')
        (self.source/'internal.txt').symlink_to('receipt.txt')
        self.destination=self.root/'history'/'retry'/'chatgpt';self.destination.parent.mkdir(parents=True)

    def test_move_and_rollback_preserve_bytes_and_link_destinations(self):
        move(self.source,self.destination)
        self.assertEqual((self.destination/'relative.txt').resolve(),self.target.resolve())
        self.assertEqual((self.destination/'internal.txt').read_bytes(),b'original receipt')
        self.assertEqual(os.readlink(self.destination/'absolute.txt'),str(self.target))
        move(self.destination,self.source)
        self.assertEqual((self.source/'relative.txt').resolve(),self.target.resolve())
        self.assertEqual(self.target.read_bytes(),b'immutable evidence')

    def test_crash_after_rename_resumes_without_replacing_changed_evidence(self):
        replace=os.replace
        def interrupt(source,target):
            if str(target).endswith('.json'):return replace(source,target)
            raise OSError('Interrupted')
        with patch('core.archive_paths.os.replace',side_effect=interrupt):
            with self.assertRaises(OSError):move(self.source,self.destination)
        self.assertFalse(self.source.exists());self.assertTrue(self.destination.exists())
        move(self.source,self.destination)
        self.assertEqual((self.destination/'relative.txt').read_bytes(),b'immutable evidence')
        self.assertFalse(self.destination.with_name('.chatgpt.links-move.json').exists())

    def test_changed_link_and_conflicting_destination_block_move(self):
        replace=os.replace
        def interrupt(source,target):
            if str(target).endswith('.json'):return replace(source,target)
            raise OSError('Interrupted')
        with patch('core.archive_paths.os.replace',side_effect=interrupt):
            with self.assertRaises(OSError):move(self.source,self.destination)
        link=self.destination/'relative.txt';link.unlink();link.symlink_to('../foreign')
        with self.assertRaisesRegex(ValueError,'变化'):move(self.source,self.destination)
        self.assertEqual(os.readlink(link),'../foreign')


if __name__=='__main__':unittest.main()
