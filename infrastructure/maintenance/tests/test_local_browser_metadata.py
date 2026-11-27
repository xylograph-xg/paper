"""Local browser metadata ignores proxy configuration and never contacts WAN."""
import io
import unittest
from unittest.mock import Mock, patch

from maintenance.web_tab_watch import _local_targets


class LocalBrowserMetadata(unittest.TestCase):
    def test_loopback_inventory_uses_an_explicitly_empty_proxy_handler(self):
        opener=Mock();opener.open.return_value=io.BytesIO(b'[{"id":"owned","type":"page"}]')
        with (patch.dict('os.environ',{'HTTP_PROXY':'http://unavailable.invalid:7890'}),
              patch('maintenance.web_tab_watch.urllib.request.build_opener',return_value=opener) as build):
            self.assertEqual(_local_targets('http://127.0.0.1:9222/')[0]['id'],'owned')
        self.assertEqual(build.call_args.args[0].proxies,{})
        opener.open.assert_called_once_with('http://127.0.0.1:9222/json/list',timeout=5)

    def test_metadata_rejects_nonlocal_origins_and_ambiguous_urls(self):
        for endpoint in ['http://example.com:9222','file:///tmp/private','http://127.0.0.1',
                         'http://user:password@127.0.0.1:9222','http://127.0.0.1:9222/private',
                         'http://127.0.0.1:9222?forward=secret']:
            with self.subTest(endpoint=endpoint),patch('maintenance.web_tab_watch.urllib.request.build_opener') as build:
                with self.assertRaises(ValueError):_local_targets(endpoint)
                build.assert_not_called()
