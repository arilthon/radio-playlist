import unittest
from unittest.mock import Mock
from matching import choose_track, search_artist
from radio import processar


def track(artists, title, version=''):
    return {'id':'123', '_artists':artists, 'attributes':{'title':title,'version':version}}


class SlashArtistTests(unittest.TestCase):
    def test_repeated_artist(self):
        t = track(['The Weeknd'],'Save Your Tears')
        self.assertEqual(choose_track('THE WEEKND/THE WEEKND','SAVE YOUR TEARS',[t]), (t,1))
        self.assertEqual(search_artist('THE WEEKND/THE WEEKND'),'the weeknd')

    def test_collaboration_and_featured_title(self):
        t = track(['Travie McCoy','Bruno Mars'],'Billionaire (feat. Bruno Mars)')
        self.assertEqual(choose_track('TRAVIE MCCOY/BRUNO MARS','BILLIONAIRE',[t]), (t,1))
        client=Mock()
        client.search.return_value=[t]
        client.playlist_tracks.return_value=set()
        processar(client,'playlist','TRAVIE MCCOY/BRUNO MARS - BILLIONAIRE')
        client.add_track.assert_called_once_with('playlist','123')

    def test_guest_only_and_wrong_versions_still_rejected(self):
        for t in [track(['Bruno Mars'],'Billionaire'),
                  track(['Someone Else'],'Billionaire'),
                  track(['Travie McCoy','Bruno Mars'],'Billionaire (feat. Bruno Mars)', 'Remix'),
                  track(['Travie McCoy','Bruno Mars'],'Other Song (feat. Bruno Mars)')]:
            self.assertIsNone(choose_track('TRAVIE MCCOY/BRUNO MARS','BILLIONAIRE',[t])[0])

    def test_literal_slashes_and_live_versions(self):
        for artist,title in [('AC/DC','Back In Black'),('Artist','Title/Subtitle')]:
            t=track([artist],title)
            self.assertEqual(choose_track(artist,title,[t]),(t,1))
        t=track(['Travie McCoy','Bruno Mars'],'Billionaire (feat. Bruno Mars) (Live)')
        self.assertEqual(choose_track('TRAVIE MCCOY/BRUNO MARS','BILLIONAIRE',[t])[0],t)
