import time
import unittest
from history import History
from radio_status import summarize


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.h=History(':memory:')
        self.addCleanup(self.h.close)

    def test_indicators_are_24h_and_queue_separated(self):
        self.h.record('p','A','adicionada','1')
        self.h.record('p','B','incerta')
        self.h.db.execute("UPDATE events SET created_at=datetime('now','-2 days') WHERE status='incerta'")
        self.h.db.commit()
        self.h.enqueue('p','A',False)
        self.h.enqueue('p','B',True)
        m=self.h.indicators()
        self.assertEqual(m['last24'].get('incerta',0),0)
        self.assertEqual(m['last24']['adicionada'],1)
        self.assertEqual((m['queue_real'],m['queue_dry']),(1,1))
        self.assertIsNotNone(m['oldest_pending'])

    def test_rate_wait_capture_independent_and_stale_not_active_when_stopped(self):
        self.h.activity('capture','listening')
        self.h.activity('worker','rate_limited',retry_at=time.time()+120)
        state=summarize(True,self.h.activities(),self.h.indicators())
        self.assertEqual(state['capture']['status'],'listening')
        self.assertGreater(state['worker']['retry_seconds'],110)
        self.assertTrue(state['alerts'])
        stopped=summarize(False,self.h.activities(),self.h.indicators())
        self.assertEqual(stopped['worker']['status'],'stopped')
        self.assertEqual(stopped['worker']['retry_seconds'],0)

    def test_no_recent_stream_and_mode_mismatch(self):
        self.h.enqueue('p','A',False)
        activities={'capture':{'status':'listening','updated':time.time()-60},'session':{'mode':'dry'}}
        state=summarize(True,activities,self.h.indicators())
        self.assertEqual(state['capture']['status'],'stale')
        self.assertTrue(any('simulação' in a for a in state['alerts']))

    def test_error_remains_visible_after_exit(self):
        self.h.activity('worker','error',message='Login expirado.')
        state=summarize(False,self.h.activities(),self.h.indicators())
        self.assertIn('Login expirado.',state['alerts'])
