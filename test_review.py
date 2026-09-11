import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dashboard import Controller
from history import History
from pipeline import process_next
from radio import processar


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'history.sqlite3'
        self.h = History(self.path)
        self.addCleanup(self.h.close)
        self.h.record('playlist', 'Artist - Song', 'incerta')
        self.event_id = self.h.db.execute('SELECT max(id) FROM events').fetchone()[0]

    def test_choice_persists_bypasses_search_and_obeys_dry_run(self):
        self.h.requeue(self.event_id, True, '123', 'Artist — Song live')
        other = History(self.path)
        self.addCleanup(other.close)
        self.assertEqual(other.choice(' ARTIST  - SONG ')['id'], '123')
        client = Mock()
        client.country = 'BR'
        client.request.return_value = {'data': {'type':'tracks','id':'123','attributes':{'title':'Song'}}}
        client.playlist_tracks.return_value = set()
        process_next(client,'playlist',other,True,processar)
        client.search.assert_not_called()
        client.add_track.assert_not_called()
        self.assertFalse(other.contains('playlist','123'))
        processar(client,'playlist','Artist - Song',False,other)
        client.add_track.assert_called_once_with('playlist','123')
        processar(client,'playlist','Artist - Song',False,other)
        client.add_track.assert_called_once()
        other.forget('Artist - Song')
        self.assertIsNone(other.choice('Artist - Song'))

    def test_requeue_during_processing_is_preserved(self):
        self.h.enqueue('playlist','Artist - Song')
        job = self.h.next_pending('playlist')
        self.h.requeue(self.event_id,False)
        self.h.finish(job[0],job[2])
        self.assertIsNotNone(self.h.next_pending('playlist'))
        new = self.h.next_pending('playlist')
        self.h.finish(new[0],new[2])
        self.assertIsNone(self.h.next_pending('playlist'))

    def test_review_candidates_resolve_and_existing_history(self):
        self.h.save_candidates('playlist','Artist - Song',[{'id':'12','attributes':{'title':'Song'}}])
        items = self.h.review_items()
        self.assertEqual(items[0]['candidates'][0]['id'],'12')
        self.h.record('playlist','Artist - Song','adicionada','12')
        self.assertEqual(self.h.review_items(),[])

    def test_approve_url_and_profile_isolation(self):
        with patch('dashboard.ROOT',Path(self.folder.name)):
            c = Controller()
            c.review_action('approve',dict(event_id=self.event_id,track='https://tidal.com/browse/track/123?u=x',mode='dry'))
            self.assertEqual(self.h.choice('Artist - Song')['id'],'123')
            self.assertIsNone(self.h.next_pending('playlist',False))
            self.assertIsNotNone(self.h.next_pending('playlist',True))
            other = Controller('123456789abc')
            with self.assertRaises(ValueError):
                other.review_action('reprocess',dict(event_id=self.event_id))
            with self.assertRaises(ValueError):
                c.review_action('approve',dict(event_id=self.event_id,track='https://evil.test/track/123'))

    def test_invalid_track_not_written_or_learned(self):
        with self.assertRaises(ValueError):
            self.h.requeue(self.event_id,False,'bad')
        self.assertIsNone(self.h.choice('Artist - Song'))
        self.assertIsNone(self.h.next_pending('playlist'))

    def test_manual_choice_can_resolve_unstructured_metadata(self):
        self.h.record('playlist','Arquivo_sem_artista','ignorada')
        event_id = self.h.db.execute('SELECT max(id) FROM events').fetchone()[0]
        self.h.requeue(event_id,True,'123')
        client = Mock()
        client.country='BR'
        client.request.return_value={'data':{'type':'tracks','id':'123'}}
        client.playlist_tracks.return_value=set()
        processar(client,'playlist','Arquivo_sem_artista',True,self.h)
        client.search.assert_not_called()
        client.request.assert_called_once()
