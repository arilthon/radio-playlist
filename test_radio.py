import io
import unittest
from unittest.mock import Mock, patch

from radio import obter_metadados_icecast, playlist_id, processar, read_exact


class RadioTests(unittest.TestCase):
    def test_truncated_stream(self):
        with self.assertRaises(EOFError):
            read_exact(io.BytesIO(b'a'), 2)

    def test_metadata_after_empty_block_with_semicolon_and_accent(self):
        raw = "StreamTitle='Artista - Canção; ao vivo';".encode('latin-1')
        size = (len(raw) + 15) // 16
        stream = io.BytesIO(b'abc\0abc' + bytes([size]) + raw.ljust(size * 16, b'\0'))
        stream.headers = {'icy-metaint': '3'}
        with patch('radio.urllib.request.urlopen', return_value=stream):
            self.assertEqual(obter_metadados_icecast('https://radio.test'), 'Artista - Canção; ao vivo')

    def test_missing_icy_header(self):
        stream = io.BytesIO()
        stream.headers = {}
        with patch('radio.urllib.request.urlopen', return_value=stream):
            with self.assertRaises(ValueError):
                obter_metadados_icecast('https://radio.test')

    def test_playlist_url(self):
        uid = '550e8400-e29b-41d4-a716-446655440000'
        self.assertEqual(playlist_id('https://tidal.com/browse/playlist/' + uid + '?u=x'), uid)
        with self.assertRaises(ValueError):
            playlist_id('invalid')

    def test_dry_run_and_write(self):
        client = Mock()
        client.search.return_value = [{'id': '123', 'attributes': {'title': 'Song'}, '_artists': ['Artist']}]
        client.playlist_tracks.return_value = set()
        processar(client, 'playlist', 'Artist - Song', True)
        client.add_track.assert_not_called()
        processar(client, 'playlist', 'Artist - Song')
        client.add_track.assert_called_once_with('playlist', '123')

    def test_no_match_does_not_write(self):
        client = Mock()
        client.search.return_value = []
        processar(client, 'playlist', 'Artist - Song')
        client.add_track.assert_not_called()


if __name__ == '__main__':
    unittest.main()
