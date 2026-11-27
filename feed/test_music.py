from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from . import music
from .models import Entry

User = get_user_model()


def apple_song(track_id=1, name='Get Lucky', artist='Daft Punk', **extra):
    """One item shaped like Apple's iTunes Search answer."""
    item = {
        'wrapperType': 'track', 'kind': 'song', 'trackId': track_id,
        'trackName': name, 'artistName': artist, 'collectionName': 'RAM',
        'artworkUrl100': 'https://is1-ssl.mzstatic.com/image/thumb/x/100x100bb.jpg',
        'previewUrl': 'https://audio-ssl.itunes.apple.com/p/clip.m4a',
        'trackViewUrl': 'https://music.apple.com/us/album/get-lucky/1?i=1',
    }
    item.update(extra)
    return item


def answer(*items):
    return {'resultCount': len(items), 'results': list(items)}


class MusicBase(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('ann', password='pw')
        self.client.force_login(self.user)


class SearchTests(MusicBase):
    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('music_search'), {'q': 'daft'}).status_code, 302)

    def test_short_query_makes_no_request(self):
        with mock.patch('feed.music._fetch') as fetch:
            r = self.client.get(reverse('music_search'), {'q': ' a '})
        fetch.assert_not_called()
        self.assertEqual(r.json(), {'results': []})

    def test_returns_clean_results_and_caches(self):
        with mock.patch('feed.music._fetch', return_value=answer(apple_song())) as fetch:
            first = self.client.get(reverse('music_search'), {'q': 'get lucky'}).json()
            again = self.client.get(reverse('music_search'), {'q': '  GET   lucky '}).json()
        self.assertEqual(fetch.call_count, 1)             # second answer came from the cache
        self.assertEqual(first, again)
        song = first['results'][0]
        self.assertEqual((song['id'], song['title'], song['artist']), ('1', 'Get Lucky', 'Daft Punk'))
        self.assertIn('100x100bb', song['art'])
        self.assertNotIn('url', song)

    def test_drops_things_that_are_not_songs_or_have_foreign_links(self):
        items = [
            apple_song(1),
            apple_song(2, kind='music-video'),
            apple_song(3, name=''),
            apple_song(4, previewUrl='javascript:alert(1)', artworkUrl100='https://evil.example/100x100bb.jpg'),
            apple_song(5, trackViewUrl='https://apple.com.evil.example/x'),
            apple_song('abc'),
        ]
        with mock.patch('feed.music._fetch', return_value=answer(*items)):
            results = music.search('whatever')
        self.assertEqual([s['id'] for s in results], ['1', '4', '5'])
        self.assertEqual(results[1]['preview'], '')
        self.assertEqual(results[1]['art'], '')
        self.assertEqual(results[2]['url'], '')

    def test_apple_down_gives_502_with_message(self):
        with mock.patch('feed.music._fetch', side_effect=music.MusicError('Music search is busy.')):
            r = self.client.get(reverse('music_search'), {'q': 'daft'})
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()['error'], 'Music search is busy.')

    def test_per_member_throttle(self):
        with mock.patch('feed.music.SEARCHES_PER_MINUTE', 2), \
             mock.patch('feed.music._fetch', return_value=answer(apple_song())):
            codes = [self.client.get(reverse('music_search'), {'q': f'song {i}'}).status_code
                     for i in range(4)]
        self.assertEqual(codes, [200, 200, 429, 429])

    def test_post_not_allowed(self):
        self.assertEqual(self.client.post(reverse('music_search'), {'q': 'daft'}).status_code, 405)


class LookupTests(MusicBase):
    def test_rejects_non_numeric_without_calling_apple(self):
        with mock.patch('feed.music._fetch') as fetch:
            self.assertIsNone(music.lookup('1; DROP'))
            self.assertIsNone(music.lookup(''))
        fetch.assert_not_called()

    def test_uses_big_artwork(self):
        with mock.patch('feed.music._fetch', return_value=answer(apple_song())):
            song = music.lookup('1')
        self.assertIn('300x300bb', song['art'])

    def test_unknown_id_is_none_and_remembered(self):
        with mock.patch('feed.music._fetch', return_value=answer()) as fetch:
            self.assertIsNone(music.lookup('99'))
            self.assertIsNone(music.lookup('99'))
        self.assertEqual(fetch.call_count, 1)


class PostWithMusicTests(MusicBase):
    def publish(self, **data):
        body = {'title': 'T', 'body': 'B', 'submit_token': '7b4f2c1e-0000-4000-8000-000000000001'}
        body.update(data)
        return self.client.post(reverse('post_create'), body)

    def test_form_shows_music_box(self):
        html = self.client.get(reverse('post_create')).content.decode()
        self.assertIn('data-music', html)
        self.assertIn('music_pick.js', html)

    def test_song_is_saved_from_apple_data_not_from_the_browser(self):
        with mock.patch('feed.music._fetch', return_value=answer(apple_song())):
            r = self.publish(music='1', music_title='FORGED', music_url='https://evil.example')
        entry = Entry.objects.get()
        self.assertRedirects(r, entry.get_absolute_url())
        self.assertEqual((entry.music_id, entry.music_title, entry.music_artist),
                         ('1', 'Get Lucky', 'Daft Punk'))
        self.assertTrue(entry.music_url.startswith('https://music.apple.com/'))
        self.assertIn('300x300bb', entry.music_art)

    def test_post_without_music_still_works_and_makes_no_request(self):
        with mock.patch('feed.music._fetch') as fetch:
            self.publish()
        fetch.assert_not_called()
        self.assertEqual(Entry.objects.get().music_id, '')

    def test_bad_or_unknown_id_blocks_the_post(self):
        with mock.patch('feed.music._fetch', return_value=answer()):
            r = self.publish(music='99')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'could not find that song')
        self.assertFalse(Entry.objects.exists())
        r = self.publish(music='abc', submit_token='7b4f2c1e-0000-4000-8000-000000000002')
        self.assertContains(r, 'could not find that song')
        self.assertFalse(Entry.objects.exists())

    def test_apple_down_blocks_the_post_with_a_message(self):
        with mock.patch('feed.music._fetch', side_effect=music.MusicError('Music search is not available right now.')):
            r = self.publish(music='1')
        self.assertContains(r, 'not available right now')
        self.assertContains(r, 'remove the song')
        self.assertFalse(Entry.objects.exists())

    def test_chosen_song_is_kept_when_another_field_is_wrong(self):
        with mock.patch('feed.music._fetch', return_value=answer(apple_song())):
            r = self.publish(music='1', title='')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Get Lucky')
        self.assertContains(r, 'name="music" value="1"')
        self.assertFalse(Entry.objects.exists())

    def test_tweets_cannot_have_music(self):
        from django.core.exceptions import ValidationError
        entry = Entry(author=self.user, kind=Entry.Kind.TWEET, body='hi', music_id='1')
        with self.assertRaises(ValidationError):
            entry.full_clean()


class ShowMusicTests(MusicBase):
    def make(self, **extra):
        return Entry.objects.create(
            author=self.user, kind=Entry.Kind.POST, title='T', body='B',
            music_id='1', music_title='Get <i>Lucky</i>', music_artist='Daft Punk',
            music_art='https://is1-ssl.mzstatic.com/a/300x300bb.jpg',
            music_preview='https://audio-ssl.itunes.apple.com/p/clip.m4a',
            music_url='https://music.apple.com/us/album/x/1', **extra)

    def test_detail_home_and_profile_show_the_song(self):
        entry = self.make()
        for url in (entry.get_absolute_url(), reverse('home'), reverse('profile', args=['ann'])):
            html = self.client.get(url).content.decode()
            self.assertIn('music-card', html, url)
            self.assertIn('Get &lt;i&gt;Lucky&lt;/i&gt;', html, url)      # escaped
            self.assertIn('<audio', html, url)
            self.assertIn('clip.m4a', html, url)

    def test_no_card_without_music(self):
        Entry.objects.create(author=self.user, kind=Entry.Kind.POST, title='T', body='B')
        self.assertNotIn('music-card', self.client.get(reverse('home')).content.decode())
