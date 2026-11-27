from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from feed.models import Entry

User = get_user_model()


class PrivacyTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner', password='pw')
        self.other = User.objects.create_user('other', password='pw')
        self.post = Entry.objects.create(
            author=self.owner, kind='post', title='Hello post', body='post body')
        self.tweet = Entry.objects.create(author=self.owner, kind='tweet', body='my tweet text')
        self.comment = Entry.objects.create(
            author=self.owner, kind='tweet', body='my comment', parent=self.post)
        self.url = reverse('profile', args=['owner'])

    def set_privacy(self, public=True, posts=True, tweets=True):
        p = self.owner.profile
        p.is_public, p.public_posts, p.public_tweets = public, posts, tweets
        p.save()

    def test_private_by_default_sends_visitors_to_login(self):
        for url in (self.url, self.post.get_absolute_url(), self.tweet.get_absolute_url()):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302)
            self.assertIn('/accounts/login/', r['Location'])

    def test_missing_user_looks_the_same_as_private(self):
        r = self.client.get(reverse('profile', args=['nobody']))
        self.assertEqual(r.status_code, 302)

    def test_public_profile_shows_posts_and_tweets(self):
        self.set_privacy()
        r = self.client.get(self.url + '?kind=all')
        self.assertContains(r, 'Hello post')
        self.assertContains(r, 'my tweet text')
        self.assertContains(r, 'Log in to follow')

    def test_hiding_posts(self):
        self.set_privacy(posts=False)
        r = self.client.get(self.url + '?kind=all')
        self.assertNotContains(r, 'Hello post')
        self.assertContains(r, 'my tweet text')
        self.assertEqual(self.client.get(self.post.get_absolute_url()).status_code, 302)
        self.assertEqual(self.client.get(self.tweet.get_absolute_url()).status_code, 200)

    def test_hiding_tweets(self):
        self.set_privacy(tweets=False)
        r = self.client.get(self.url + '?kind=tweet')   # falls back to the posts tab
        self.assertContains(r, 'Hello post')
        self.assertNotContains(r, 'my tweet text')
        self.assertEqual(self.client.get(self.tweet.get_absolute_url()).status_code, 302)

    def test_hiding_both_shows_a_note(self):
        self.set_privacy(posts=False, tweets=False)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'for members only')

    def test_public_post_hides_comments_from_private_tweeters(self):
        self.set_privacy(tweets=False)
        r = self.client.get(self.post.get_absolute_url())
        self.assertContains(r, 'Hello post')
        self.assertNotContains(r, 'my comment')

    def test_visitor_cannot_comment_or_like(self):
        self.set_privacy()
        r = self.client.post(self.post.get_absolute_url(), {'body': 'sneaky'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Entry.objects.filter(body='sneaky').exists())
        r = self.client.post(reverse('like_toggle', args=[self.post.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/accounts/login/', r['Location'])

    def test_members_always_see_private_profiles(self):
        self.client.login(username='other', password='pw')
        r = self.client.get(self.url + '?kind=all')
        self.assertContains(r, 'Hello post')
        self.assertContains(r, 'my tweet text')

    def test_other_pages_still_need_login(self):
        for name in ('home', 'explore', 'tweets', 'settings'):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302, name)


class SettingsPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('sam', password='pw')
        self.client.login(username='sam', password='pw')

    def test_page_loads(self):
        self.assertContains(self.client.get(reverse('settings')), 'Privacy')

    def test_saving_the_switches(self):
        r = self.client.post(reverse('settings'), {'is_public': 'on', 'public_tweets': 'on'})
        self.assertRedirects(r, reverse('settings'))
        p = self.user.profile
        p.refresh_from_db()
        self.assertEqual((p.is_public, p.public_posts, p.public_tweets), (True, False, True))

    def test_unticking_everything_makes_it_private(self):
        self.user.profile.is_public = True
        self.user.profile.save()
        self.client.post(reverse('settings'), {})
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.is_public)


class ThemeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('sam', password='pw')

    def test_default_is_light_and_member_pages_carry_the_theme(self):
        self.client.login(username='sam', password='pw')
        self.assertContains(self.client.get(reverse('home')), '<html lang="en" data-theme="light">')

    def test_saving_a_theme(self):
        self.client.login(username='sam', password='pw')
        for choice in ('dark', 'system', 'light'):
            self.client.post(reverse('settings'), {'theme': choice})
            self.user.profile.refresh_from_db()
            self.assertEqual(self.user.profile.theme, choice)
            self.assertContains(self.client.get(reverse('explore')), f'data-theme="{choice}"')

    def test_a_made_up_theme_is_refused(self):
        self.client.login(username='sam', password='pw')
        r = self.client.post(reverse('settings'), {'theme': 'neon'})
        self.assertEqual(r.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.theme, 'light')

    def test_privacy_save_without_a_theme_keeps_the_theme(self):
        self.user.profile.theme = 'dark'
        self.user.profile.save()
        self.client.login(username='sam', password='pw')
        self.client.post(reverse('settings'), {'is_public': 'on'})
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.theme, 'dark')

    def test_visitors_get_no_theme_and_no_top_bar_on_a_profile(self):
        self.user.profile.is_public = True
        self.user.profile.theme = 'dark'
        self.user.profile.save()
        page = self.client.get(reverse('profile', args=['sam']))
        self.assertNotContains(page, 'data-theme')          # the owner's theme is only for the owner
        self.assertNotContains(page, 'site-header')

    def test_members_still_have_the_top_bar_markup_on_a_profile(self):
        other = User.objects.create_user('kim', password='pw')
        self.client.login(username='kim', password='pw')
        self.assertContains(self.client.get(reverse('profile', args=['sam'])), 'site-header')
