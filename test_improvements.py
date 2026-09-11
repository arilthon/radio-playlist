import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from history import History
from matching import choose_track
from radio import processar
from tidal_client import TidalClient


def track(id='1', artist='Artist', title='Song', version=''):
    return {'id': id, '_artists': [artist], 'attributes': {'title': title, 'version': version}}


class ImprovementsTests(unittest.TestCase):
    def test_matching_rejects_wrong_artist_and_version(self):
        good = track('3')
        selected, score = choose_track('Artist', 'Song', [track(artist='Other'), track(version='Live'), good])
        self.assertEqual(selected, good)
        self.assertEqual(score, 1)
        self.assertIsNone(choose_track('Artist', 'Song', [track(artist='Other'), track(version='Remix')])[0])
        self.assertIsNotNone(choose_track('Regis Danese', 'Compromisso', [track(artist='Régis Danese', title='Compromisso')])[0])

    def test_radio_group_prefix_and_word_boundaries(self):
        self.assertIsNotNone(choose_track('Grupo Logos', 'Portas Abertas', [track(artist='Logos', title='Portas Abertas')])[0])
        self.assertIsNone(choose_track('Grupo Logos', 'Portas Abertas', [track(artist='Outro', title='Portas Abertas')])[0])
        self.assertIsNotNone(choose_track('Artist', 'Alive', [track(title='Alive')])[0])

    def test_live_fallback_and_studio_preference(self):
        for live in [track('live', version='Ao Vivo'), track('live', title='Song (Live)'),
                     track('live', title='Song - Ao Vivo'), track('live', title='Song [Live at Wembley]')]:
            self.assertEqual(choose_track('Artist', 'Song', [live])[0], live)
            studio = track('studio')
            self.assertEqual(choose_track('Artist', 'Song', [live, studio])[0], studio)
            self.assertEqual(choose_track('Artist', 'Song (Ao Vivo)', [studio, live])[0], live)
        self.assertIsNone(choose_track('Artist', 'Song', [track(artist='Other', version='Live')])[0])
        self.assertIsNone(choose_track('Artist', 'Song', [track(version='Live Remix')])[0])
        self.assertIsNotNone(choose_track('Artist', 'Live Forever', [track(title='Live Forever')])[0])

    def test_persistence_and_playlist_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'history.db'
            h = History(path)
            client = Mock()
            client.search.return_value = [track()]
            client.playlist_tracks.return_value = set()
            processar(client, 'a', 'Artist - Song', history=h)
            h.close()
            h = History(path)
            processar(client, 'a', 'Artist - Song', history=h)
            client.add_track.assert_called_once()
            processar(client, 'b', 'Artist - Song', history=h)
            self.assertEqual(client.add_track.call_count, 2)
            self.assertIn('duplicada', [row[1] for row in h.recent()])
            h.close()

    def test_remote_duplicate_and_dry_run(self):
        client = Mock()
        client.search.return_value = [track()]
        client.playlist_tracks.return_value = {'1'}
        processar(client, 'a', 'Artist - Song')
        client.add_track.assert_not_called()
        client.playlist_tracks.return_value = set()
        processar(client, 'a', 'Artist - Song', dry_run=True)
        client.add_track.assert_not_called()

    def test_failed_add_is_not_marked_added(self):
        h = History(':memory:')
        self.addCleanup(h.close)
        client = Mock()
        client.search.return_value = [track()]
        client.playlist_tracks.return_value = set()
        client.add_track.side_effect = RuntimeError('offline')
        with self.assertRaises(RuntimeError):
            processar(client, 'a', 'Artist - Song', history=h)
        self.assertFalse(h.contains('a', '1'))
        self.assertEqual(h.recent()[0][1], 'erro')

    def test_all_playlist_pages_checked(self):
        client = object.__new__(TidalClient)
        client.country = 'BR'
        client.request = Mock(side_effect=[
            {'data': [{'type': 'tracks', 'id': '1'}], 'links': {'next': '?page%5Bcursor%5D=next'}},
            {'data': [{'type': 'tracks', 'id': '2'}], 'links': {}},
        ])
        self.assertEqual(client.playlist_tracks('a'), {'1', '2'})
        self.assertEqual(client.request.call_args.kwargs['params']['page[cursor]'], 'next')
