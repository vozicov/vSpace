from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

FORM = {'display_name': '', 'bio': '', 'avatar_shape': 'circle',
        'background_color': '#f3f4f6', 'card_color': '#ffffff'}


class ProfileFontTests(TestCase):
    def setUp(self):
        self.ann = User.objects.create_user('ann', password='pw')
        self.client.force_login(self.ann)

    def test_font_is_saved_and_applied_to_the_profile_card(self):
        r = self.client.post(reverse('profile_edit'), {**FORM, 'font': 'pacifico'})
        self.assertRedirects(r, reverse('profile', args=['ann']))
        self.ann.profile.refresh_from_db()
        self.assertEqual(self.ann.profile.font, 'pacifico')
        self.assertContains(self.client.get(reverse('profile', args=['ann'])),
                            'class="profile-card font-pacifico"')

    def test_unknown_font_is_rejected(self):
        r = self.client.post(reverse('profile_edit'), {**FORM, 'font': 'comic-sans'})
        self.assertEqual(r.status_code, 200)
        self.ann.profile.refresh_from_db()
        self.assertEqual(self.ann.profile.font, 'default')

    def test_every_font_is_offered_on_the_edit_page(self):
        r = self.client.get(reverse('profile_edit'))
        for key in ('default', 'inter', 'playfair', 'spacemono', 'pacifico', 'lobster',
                    'dancing', 'caveat', 'marker', 'bebas', 'pixel'):
            self.assertContains(r, f'font-{key}')

    def test_visitors_see_the_owners_font(self):
        self.ann.profile.font = 'lobster'
        self.ann.profile.save()
        bob = User.objects.create_user('bob', password='pw')
        self.client.force_login(bob)
        self.assertContains(self.client.get(reverse('profile', args=['ann'])), 'font-lobster')
