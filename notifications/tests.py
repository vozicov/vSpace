from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Follow
from feed.models import Entry, Like

from .models import Notification

User = get_user_model()


class NotificationTests(TestCase):
    def setUp(self):
        self.ann = User.objects.create_user('ann', password='pw')
        self.bob = User.objects.create_user('bob', password='pw')
        self.post = Entry.objects.create(author=self.ann, kind='post', title='Sunset', body='x')

    def mine(self, user, kind=None):
        qs = Notification.objects.filter(recipient=user)
        return qs.filter(kind=kind) if kind else qs

    # ----- follows -----
    def test_follow_and_unfollow(self):
        Follow.objects.create(follower=self.bob, following=self.ann)
        self.assertEqual(self.mine(self.ann, 'follow').count(), 1)
        Follow.objects.get(follower=self.bob).delete()
        self.assertEqual(self.mine(self.ann).count(), 0)

    def test_following_through_the_site(self):
        self.client.login(username='bob', password='pw')
        self.client.post(reverse('follow_toggle', args=['ann']))
        self.assertEqual(self.mine(self.ann, 'follow').get().actor, self.bob)
        self.client.post(reverse('follow_toggle', args=['ann']))
        self.assertEqual(self.mine(self.ann).count(), 0)

    # ----- likes -----
    def test_like_and_unlike(self):
        self.client.login(username='bob', password='pw')
        self.client.post(reverse('like_toggle', args=[self.post.pk]))
        n = self.mine(self.ann, 'like').get()
        self.assertEqual((n.actor, n.entry), (self.bob, self.post))
        self.client.post(reverse('like_toggle', args=[self.post.pk]))
        self.assertEqual(self.mine(self.ann).count(), 0)

    def test_liking_your_own_post_tells_nobody(self):
        Like.objects.create(user=self.ann, entry=self.post)
        self.assertEqual(Notification.objects.count(), 0)

    def test_two_likers_two_notifications(self):
        Like.objects.create(user=self.bob, entry=self.post)
        Like.objects.create(user=User.objects.create_user('cy', password='pw'), entry=self.post)
        self.assertEqual(self.mine(self.ann, 'like').count(), 2)

    # ----- comments -----
    def test_comment_on_a_post(self):
        self.client.login(username='bob', password='pw')
        self.client.post(self.post.get_absolute_url(), {'body': 'lovely'})
        n = self.mine(self.ann, 'comment').get()
        self.assertEqual(n.entry.parent, self.post)

    def test_reply_goes_to_the_author_of_the_comment(self):
        c = Entry.objects.create(author=self.bob, kind='tweet', body='first', parent=self.post)
        Entry.objects.create(author=self.ann, kind='tweet', body='thanks', parent=c)
        self.assertEqual(self.mine(self.bob, 'comment').count(), 1)

    def test_commenting_on_yourself_and_plain_tweets_make_none(self):
        Entry.objects.create(author=self.ann, kind='tweet', body='me', parent=self.post)
        Entry.objects.create(author=self.bob, kind='tweet', body='hello world')
        self.assertEqual(Notification.objects.count(), 0)

    def test_deleting_the_comment_or_post_removes_the_notification(self):
        c = Entry.objects.create(author=self.bob, kind='tweet', body='hi', parent=self.post)
        c.delete()
        self.assertEqual(Notification.objects.count(), 0)
        Like.objects.create(user=self.bob, entry=self.post)
        self.post.delete()
        self.assertEqual(Notification.objects.count(), 0)

    # ----- the page -----
    def test_page_lists_marks_read_and_the_badge_follows(self):
        Follow.objects.create(follower=self.bob, following=self.ann)
        Like.objects.create(user=self.bob, entry=self.post)
        Entry.objects.create(author=self.bob, kind='tweet', body='nice one', parent=self.post)
        self.client.login(username='ann', password='pw')

        home = self.client.get(reverse('home'))
        self.assertContains(home, 'class="badge"')
        self.assertContains(home, '3 unread')

        page = self.client.get(reverse('notifications'))
        self.assertContains(page, 'started following you')
        self.assertContains(page, 'liked your post')
        self.assertContains(page, 'commented on your post')
        self.assertContains(page, 'nice one')
        self.assertContains(page, 'unread', count=None)      # highlighted on this visit
        self.assertEqual(self.mine(self.ann).filter(is_read=False).count(), 0)

        again = self.client.get(reverse('notifications'))
        self.assertNotContains(again, 'notif unread')
        self.assertNotContains(self.client.get(reverse('home')), 'class="badge"')

    def test_you_only_see_your_own(self):
        Follow.objects.create(follower=self.bob, following=self.ann)
        self.client.login(username='bob', password='pw')
        self.assertContains(self.client.get(reverse('notifications')), 'Nothing yet')

    def test_login_needed(self):
        r = self.client.get(reverse('notifications'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/accounts/login/', r['Location'])
