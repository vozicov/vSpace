import os
import shutil
import tempfile
import uuid
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Entry, Like
from .test_music import answer, apple_song

User = get_user_model()
MEDIA = tempfile.mkdtemp(prefix='space-test-media-')


def png(color='red'):
    buf = BytesIO()
    Image.new('RGB', (40, 40), color).save(buf, 'PNG')
    return SimpleUploadedFile('pic.png', buf.getvalue(), content_type='image/png')


def disk(entry, field):
    return getattr(entry, field).path


@override_settings(MEDIA_ROOT=MEDIA)
class EditDeleteBase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.ann = User.objects.create_user('ann', password='pw')
        self.bob = User.objects.create_user('bob', password='pw')
        self.client.force_login(self.ann)

    def post(self, **extra):
        data = dict(author=self.ann, kind=Entry.Kind.POST, title='Hello', body='World')
        data.update(extra)
        return Entry.objects.create(**data)

    def tweet(self, **extra):
        data = dict(author=self.ann, kind=Entry.Kind.TWEET, body='a tweet')
        data.update(extra)
        return Entry.objects.create(**data)


class EditTests(EditDeleteBase):
    def test_owner_edits_post_text_and_keeps_token(self):
        token = uuid.uuid4()
        entry = self.post(submit_token=token)
        r = self.client.post(reverse('entry_edit', args=[entry.pk]), {'title': 'New title', 'body': 'New body'})
        self.assertRedirects(r, entry.get_absolute_url())
        entry.refresh_from_db()
        self.assertEqual((entry.title, entry.body), ('New title', 'New body'))
        self.assertEqual(entry.submit_token, token)

    def test_post_needs_a_title(self):
        entry = self.post()
        r = self.client.post(reverse('entry_edit', args=[entry.pk]), {'title': '', 'body': 'x'})
        self.assertEqual(r.status_code, 200)
        entry.refresh_from_db()
        self.assertEqual(entry.title, 'Hello')

    def test_edit_page_opens(self):
        entry = self.post()
        r = self.client.get(reverse('entry_edit', args=[entry.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Edit post')

    def test_edits_a_tweet_and_a_comment(self):
        tweet = self.tweet()
        comment = self.tweet(parent=tweet, body='first')
        self.client.post(reverse('entry_edit', args=[tweet.pk]), {'body': 'changed'})
        self.client.post(reverse('entry_edit', args=[comment.pk]), {'body': 'changed too'})
        tweet.refresh_from_db()
        comment.refresh_from_db()
        self.assertEqual((tweet.body, comment.body), ('changed', 'changed too'))
        self.assertEqual(comment.parent_id, tweet.pk)

    def test_tweet_stays_under_280_characters(self):
        tweet = self.tweet()
        r = self.client.post(reverse('entry_edit', args=[tweet.pk]), {'body': 'x' * 281})
        self.assertEqual(r.status_code, 200)
        tweet.refresh_from_db()
        self.assertEqual(tweet.body, 'a tweet')

    def test_nobody_else_can_edit(self):
        entry = self.post()
        self.client.force_login(self.bob)
        url = reverse('entry_edit', args=[entry.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {'title': 'hacked', 'body': 'x'}).status_code, 404)
        entry.refresh_from_db()
        self.assertEqual(entry.title, 'Hello')

    def test_login_needed(self):
        entry = self.post()
        self.client.logout()
        self.assertEqual(self.client.get(reverse('entry_edit', args=[entry.pk])).status_code, 302)

    def test_a_new_picture_replaces_the_old_files(self):
        r = self.client.post(reverse('post_create'), {'title': 'Pic', 'body': 'text', 'media': png('red'),
                                                      'submit_token': uuid.uuid4()})
        entry = Entry.objects.get(title='Pic')
        old_media, old_thumb = disk(entry, 'media'), disk(entry, 'thumbnail')
        self.assertTrue(os.path.exists(old_media) and os.path.exists(old_thumb))

        self.client.post(reverse('entry_edit', args=[entry.pk]), {'title': 'Pic', 'body': 'text', 'media': png('blue')})
        entry.refresh_from_db()
        self.assertTrue(os.path.exists(disk(entry, 'media')))
        self.assertNotEqual(disk(entry, 'media'), old_media)
        self.assertFalse(os.path.exists(old_media))
        self.assertFalse(os.path.exists(old_thumb))

    def test_removing_the_picture_deletes_its_files(self):
        self.client.post(reverse('post_create'), {'title': 'Pic', 'body': 'text', 'media': png(),
                                                  'submit_token': uuid.uuid4()})
        entry = Entry.objects.get(title='Pic')
        old_media, old_thumb = disk(entry, 'media'), disk(entry, 'thumbnail')

        self.client.post(reverse('entry_edit', args=[entry.pk]), {'title': 'Pic', 'body': 'text', 'remove_media': 'on'})
        entry.refresh_from_db()
        self.assertEqual((entry.media.name, entry.media_type, entry.thumbnail.name), ('', '', ''))
        self.assertFalse(os.path.exists(old_media))
        self.assertFalse(os.path.exists(old_thumb))

    def test_leaving_the_picture_alone_keeps_it(self):
        self.client.post(reverse('post_create'), {'title': 'Pic', 'body': 'text', 'media': png(),
                                                  'submit_token': uuid.uuid4()})
        entry = Entry.objects.get(title='Pic')
        before = disk(entry, 'media')
        self.client.post(reverse('entry_edit', args=[entry.pk]), {'title': 'Pic 2', 'body': 'text'})
        entry.refresh_from_db()
        self.assertEqual(disk(entry, 'media'), before)
        self.assertTrue(os.path.exists(before))


class EditSongTests(EditDeleteBase):
    def song_post(self):
        return self.post(music_id='1', music_title='Get Lucky', music_artist='Daft Punk',
                         music_art='https://is1-ssl.mzstatic.com/a.jpg',
                         music_preview='https://audio-ssl.itunes.apple.com/p/clip.m4a',
                         music_url='https://music.apple.com/us/album/x/1?i=1')

    def test_same_song_is_kept_without_asking_apple(self):
        entry = self.song_post()
        with mock.patch('feed.music._fetch') as fetch:
            self.client.post(reverse('entry_edit', args=[entry.pk]), {'title': 'T', 'body': 'text', 'music': '1'})
        fetch.assert_not_called()
        entry.refresh_from_db()
        self.assertEqual((entry.music_id, entry.music_title), ('1', 'Get Lucky'))

    def test_another_song_replaces_it(self):
        entry = self.song_post()
        item = apple_song(track_id=2, name='Other', artist='Someone')
        with mock.patch('feed.music._fetch', return_value=answer(item)):
            self.client.post(reverse('entry_edit', args=[entry.pk]), {'title': 'T', 'body': 'text', 'music': '2'})
        entry.refresh_from_db()
        self.assertEqual((entry.music_id, entry.music_title, entry.music_artist), ('2', 'Other', 'Someone'))

    def test_empty_song_removes_it(self):
        entry = self.song_post()
        self.client.post(reverse('entry_edit', args=[entry.pk]), {'title': 'T', 'body': 'text', 'music': ''})
        entry.refresh_from_db()
        self.assertEqual(
            (entry.music_id, entry.music_title, entry.music_artist, entry.music_art, entry.music_preview, entry.music_url),
            ('', '', '', '', '', ''))

    def test_edit_page_shows_the_current_song(self):
        entry = self.song_post()
        r = self.client.get(reverse('entry_edit', args=[entry.pk]))
        self.assertContains(r, 'Get Lucky')
        self.assertContains(r, 'name="music" value="1"')


class DeleteTests(EditDeleteBase):
    def test_get_only_asks(self):
        entry = self.post()
        r = self.client.get(reverse('entry_delete', args=[entry.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Entry.objects.filter(pk=entry.pk).exists())

    def test_post_deletes_with_comments_and_likes(self):
        entry = self.post()
        reply = self.tweet(author=self.bob, parent=entry, body='nice')
        Like.objects.create(user=self.bob, entry=entry)
        r = self.client.post(reverse('entry_delete', args=[entry.pk]))
        self.assertRedirects(r, reverse('profile', args=['ann']), fetch_redirect_response=False)
        self.assertFalse(Entry.objects.filter(pk__in=[entry.pk, reply.pk]).exists())
        self.assertEqual(Like.objects.count(), 0)

    def test_deleting_a_tweet_goes_back_to_the_tweet_list_of_the_profile(self):
        tweet = self.tweet()
        r = self.client.post(reverse('entry_delete', args=[tweet.pk]))
        self.assertRedirects(r, reverse('profile', args=['ann']) + '?kind=tweet', fetch_redirect_response=False)

    def test_deleting_a_comment_goes_back_to_its_post(self):
        entry = self.post(author=self.bob)
        comment = self.tweet(parent=entry, body='mine')
        r = self.client.post(reverse('entry_delete', args=[comment.pk]))
        self.assertRedirects(r, entry.get_absolute_url(), fetch_redirect_response=False)
        self.assertTrue(Entry.objects.filter(pk=entry.pk).exists())

    def test_files_are_removed_from_disk(self):
        self.client.post(reverse('post_create'), {'title': 'Pic', 'body': 'text', 'media': png(),
                                                  'submit_token': uuid.uuid4()})
        entry = Entry.objects.get(title='Pic')
        media, thumb = disk(entry, 'media'), disk(entry, 'thumbnail')
        self.client.post(reverse('entry_delete', args=[entry.pk]))
        self.assertFalse(os.path.exists(media))
        self.assertFalse(os.path.exists(thumb))

    def test_nobody_else_can_delete(self):
        entry = self.post()
        self.client.force_login(self.bob)
        url = reverse('entry_delete', args=[entry.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(Entry.objects.filter(pk=entry.pk).exists())

    def test_edit_and_delete_links_only_for_the_owner(self):
        entry = self.post()
        edit, delete = reverse('entry_edit', args=[entry.pk]), reverse('entry_delete', args=[entry.pk])
        mine = self.client.get(entry.get_absolute_url())
        self.assertContains(mine, edit)
        self.assertContains(mine, delete)
        self.client.force_login(self.bob)
        theirs = self.client.get(entry.get_absolute_url())
        self.assertNotContains(theirs, edit)
        self.assertNotContains(theirs, delete)
