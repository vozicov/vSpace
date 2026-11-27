from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from feed.models import Entry

from .models import InterestPin, ShelfItem

User = get_user_model()
Kind = ShelfItem.Kind


def make_post(author, title='Post', **kw):
    return Entry.objects.create(author=author, kind=Entry.Kind.POST, title=title, body='body', **kw)


class ShelfTests(TestCase):
    def setUp(self):
        self.ann = User.objects.create_user('ann', password='pw')
        self.bob = User.objects.create_user('bob', password='pw')
        self.client.login(username='ann', password='pw')
        self.mine = make_post(self.ann, 'Mine')
        self.theirs = make_post(self.bob, 'Theirs')

    # ----- putting posts on the shelf -----

    def test_add_to_shelf_toggles(self):
        url = reverse('shelf_toggle_post', args=[self.theirs.pk])
        self.client.post(url)
        self.assertTrue(ShelfItem.objects.filter(owner=self.ann, entry=self.theirs).exists())
        self.client.post(url)
        self.assertFalse(ShelfItem.objects.filter(owner=self.ann, entry=self.theirs).exists())

    def test_tweets_cannot_go_on_the_shelf(self):
        tweet = Entry.objects.create(author=self.bob, kind=Entry.Kind.TWEET, body='hi')
        r = self.client.post(reverse('shelf_toggle_post', args=[tweet.pk]))
        self.assertEqual(r.status_code, 404)

    @override_settings(MAX_SHELF_ITEMS=1)
    def test_shelf_limit(self):
        self.client.post(reverse('shelf_toggle_post', args=[self.mine.pk]))
        self.client.post(reverse('shelf_toggle_post', args=[self.theirs.pk]))
        self.assertEqual(ShelfItem.objects.filter(owner=self.ann).count(), 1)

    def test_add_posts_picker_lists_only_own_posts_not_on_shelf(self):
        r = self.client.get(reverse('add_posts'))
        self.assertEqual([p.pk for p in r.context['posts']], [self.mine.pk])
        self.client.post(reverse('add_posts'), {'entry': [self.mine.pk, self.theirs.pk]})
        # only own posts are accepted here; the other person's post is ignored
        self.assertEqual(list(ShelfItem.objects.values_list('entry', flat=True)), [self.mine.pk])

    # ----- collections -----

    def make_collection(self, title='Faves'):
        r = self.client.post(reverse('collection_create'), {'title': title})
        item = ShelfItem.objects.get(kind=Kind.FOLDER, title=title)
        self.assertRedirects(r, reverse('collection', args=[item.pk]))
        return item

    def test_collection_needs_a_name(self):
        r = self.client.post(reverse('collection_create'), {'title': '  '})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(ShelfItem.objects.exists())

    def test_posts_go_into_a_collection(self):
        c = self.make_collection()
        self.client.post(reverse('collection_add_posts', args=[c.pk]), {'entry': [self.mine.pk]})
        item = ShelfItem.objects.get(entry=self.mine)
        self.assertEqual(item.parent, c)
        page = self.client.get(reverse('collection', args=[c.pk]))
        self.assertContains(page, 'Mine')

    def test_loose_shelf_post_can_be_moved_into_collection(self):
        self.client.post(reverse('shelf_toggle_post', args=[self.theirs.pk]))
        c = self.make_collection()
        r = self.client.get(reverse('collection_add_posts', args=[c.pk]))
        self.assertIn(self.theirs.pk, [p.pk for p in r.context['posts']])
        self.client.post(reverse('collection_add_posts', args=[c.pk]), {'entry': [self.theirs.pk]})
        self.assertEqual(ShelfItem.objects.get(entry=self.theirs).parent, c)

    def test_move_form_changes_collection(self):
        self.client.post(reverse('shelf_toggle_post', args=[self.mine.pk]))
        c = self.make_collection()
        item = ShelfItem.objects.get(entry=self.mine)
        self.client.post(reverse('item_edit', args=[item.pk]), {'parent': c.pk})
        item.refresh_from_db()
        self.assertEqual(item.parent, c)
        self.client.post(reverse('item_edit', args=[item.pk]), {'parent': ''})
        item.refresh_from_db()
        self.assertIsNone(item.parent)

    def test_rename_collection(self):
        c = self.make_collection()
        self.client.post(reverse('item_edit', args=[c.pk]), {'title': 'Renamed'})
        c.refresh_from_db()
        self.assertEqual(c.title, 'Renamed')

    def test_deleting_a_collection_keeps_the_posts(self):
        c = self.make_collection()
        self.client.post(reverse('collection_add_posts', args=[c.pk]), {'entry': [self.mine.pk]})
        self.assertContains(self.client.get(reverse('item_delete', args=[c.pk])), 'Delete collection')
        self.client.post(reverse('item_delete', args=[c.pk]))
        self.assertFalse(ShelfItem.objects.exists())
        self.assertTrue(Entry.objects.filter(pk=self.mine.pk).exists())

    def test_reorder(self):
        a, b = make_post(self.ann, 'A'), make_post(self.ann, 'B')
        self.client.post(reverse('add_posts'), {'entry': [a.pk, b.pk]})
        first, second = ShelfItem.objects.order_by('position')
        self.client.post(reverse('item_move', args=[second.pk, 'left']))
        self.assertEqual(list(ShelfItem.objects.order_by('position')), [second, first])

    # ----- other people cannot touch your shelf -----

    def test_only_the_owner_can_edit(self):
        c = self.make_collection()
        self.client.logout()
        self.client.login(username='bob', password='pw')
        for name, args in (('item_edit', [c.pk]), ('collection_add_posts', [c.pk])):
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 404)
        self.assertEqual(self.client.post(reverse('item_delete', args=[c.pk])).status_code, 404)
        self.assertTrue(ShelfItem.objects.filter(pk=c.pk).exists())
        # ...but anyone can look at it, and sees no owner controls
        page = self.client.get(reverse('collection', args=[c.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'Add posts')

    # ----- the profile page -----

    def test_profile_shows_shelf_and_collections(self):
        self.client.post(reverse('shelf_toggle_post', args=[self.theirs.pk]))
        c = self.make_collection('Faves')
        self.client.post(reverse('collection_add_posts', args=[c.pk]), {'entry': [self.mine.pk]})
        page = self.client.get(reverse('profile', args=['ann']))
        self.assertContains(page, 'Faves')
        self.assertContains(page, 'Theirs')
        self.assertContains(page, '+ Add posts')
        self.client.logout()
        self.client.login(username='bob', password='pw')
        page = self.client.get(reverse('profile', args=['ann']))
        self.assertContains(page, 'Faves')
        self.assertNotContains(page, '+ Add posts')
        self.assertNotContains(page, '+ New collection')

    def test_empty_collections_are_hidden_from_visitors(self):
        self.make_collection('Secret plans')
        self.client.logout()
        self.client.login(username='bob', password='pw')
        self.assertNotContains(self.client.get(reverse('profile', args=['ann'])), 'Secret plans')

    # ----- pins -----

    def test_pin_toggle_and_limit(self):
        self.client.post(reverse('pin_toggle', args=[self.mine.pk]))
        self.assertEqual(InterestPin.objects.filter(owner=self.ann).count(), 1)
        self.client.post(reverse('pin_toggle', args=[self.mine.pk]))
        self.assertEqual(InterestPin.objects.filter(owner=self.ann).count(), 0)

    def test_four_pins_then_replace_screen(self):
        posts = [make_post(self.ann, f'P{i}') for i in range(5)]
        for p in posts[:4]:
            self.client.post(reverse('pin_toggle', args=[p.pk]))
        r = self.client.post(reverse('pin_toggle', args=[posts[4].pk]))
        self.assertContains(r, 'Replace')
        self.client.post(reverse('pin_toggle', args=[posts[4].pk]), {'slot': 2})
        self.assertEqual(InterestPin.objects.get(owner=self.ann, slot=2).entry, posts[4])
