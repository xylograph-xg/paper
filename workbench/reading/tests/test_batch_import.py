import unittest
from unittest.mock import patch
from reading.batch_import import match_pdf


class BatchMatchingTests(unittest.TestCase):
    def setUp(self):
        self.papers=[{'id':'a','title':'Unique triplet confinement in organic host guest systems','metadata':{'doi':'10.1234/abc'}},
                     {'id':'b','title':'Other triplet transport in organic crystalline materials','metadata':{'doi':'10.1234/def'}}]

    def match(self,text):
        with patch('reading.batch_import.validate_pdf',return_value=text):
            return match_pdf('unused.pdf',self.papers)[0]

    def test_exact_identity(self):
        self.assertEqual(self.match(self.papers[0]['title']+'\n10.1234/abc'),'a')

    def test_doi_in_reference_without_title_needs_confirmation(self):
        self.assertIsNone(self.match('Supplementary Information\nReferences 10.1234/abc'))

    def test_multiple_known_dois_needs_confirmation(self):
        self.assertIsNone(self.match(self.papers[0]['title']+' 10.1234/abc 10.1234/def'))

    def test_unique_title_without_doi(self):
        self.assertEqual(self.match(self.papers[1]['title']),'b')

    def test_unknown_document(self):
        self.assertIsNone(self.match('An unrelated experimental study'))
