import unittest
from unittest.mock import Mock, patch
from rate_limit import retry_delay
from tidal_client import TidalClient


class RateLimitTests(unittest.TestCase):
    def test_retry_header_and_backoff(self):
        self.assertEqual(retry_delay('240'), 240)
        self.assertEqual(retry_delay(None), 60)
        self.assertEqual(retry_delay('bad', 3), 240)
        self.assertEqual(retry_delay('nan'), 60)
        self.assertEqual(retry_delay('-2'), 60)
        self.assertEqual(retry_delay('Wed, 01 Jan 2020 00:00:00 GMT'), 60)

    @patch('tidal_client.time.sleep')
    @patch('tidal_client.requests.request')
    def test_cache_metadata_but_not_playlist(self, request, sleep):
        client = object.__new__(TidalClient)
        client.access_token = Mock(return_value='test')
        request.return_value.json.return_value = {'data': []}
        client.request('GET', '/searchResults', params={'filter[query]': 'song'})
        client.request('GET', '/searchResults', params={'filter[query]': 'song'})
        self.assertEqual(request.call_count, 1)
        client.request('GET', '/playlists/id/relationships/items')
        client.request('GET', '/playlists/id/relationships/items')
        self.assertEqual(request.call_count, 3)
        self.assertTrue(sleep.called)

    @patch('tidal_client.requests.request')
    def test_failed_requests_are_not_cached(self, request):
        import requests
        client = object.__new__(TidalClient)
        client.access_token = Mock(return_value='test')
        request.return_value.raise_for_status.side_effect = requests.HTTPError('429')
        with self.assertRaises(requests.HTTPError):
            client.request('GET', '/searchResults')
        self.assertEqual(client._metadata_cache, {})
