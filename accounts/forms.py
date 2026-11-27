from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile

from config import media_tools as mt

from .models import BIO_MAX_LENGTH, Profile, ReferralCode

FILE_FIELDS = ('avatar', 'banner', 'background_image', 'cursor')


class ProfileForm(forms.ModelForm):
    remove_banner = forms.BooleanField(required=False, label='Remove banner')
    remove_background_image = forms.BooleanField(required=False, label='Remove background image')
    remove_cursor = forms.BooleanField(required=False, label='Remove cursor')
    # A plain file field, not an image field: Django's image check would turn away .ani files.
    # clean_cursor below reads the file properly (and rejects anything that is not a cursor).
    cursor = forms.FileField(required=False, widget=forms.FileInput(attrs={'accept': '.ani,image/*'}))

    class Meta:
        model = Profile
        fields = [
            'display_name', 'bio', 'avatar', 'avatar_shape',
            'banner', 'background_color', 'background_image', 'card_color', 'font', 'cursor',
        ]
        widgets = {
            'display_name': forms.TextInput(attrs={'placeholder': 'Your name', 'autocomplete': 'off'}),
            'bio': forms.Textarea(attrs={
                'rows': 2, 'maxlength': BIO_MAX_LENGTH, 'data-counter': '',
                'placeholder': 'A few words about you',
            }),
            'avatar': forms.FileInput(attrs={'accept': 'image/*'}),
            'avatar_shape': forms.RadioSelect,
            'font': forms.RadioSelect,
            'banner': forms.FileInput(attrs={'accept': 'image/*'}),
            'background_image': forms.FileInput(attrs={'accept': 'image/*'}),
            'background_color': forms.TextInput(attrs={'type': 'color'}),
            'card_color': forms.TextInput(attrs={'type': 'color'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Remember current files so replaced/removed ones can be deleted from disk.
        self._old_files = {name: getattr(self.instance, name).name for name in FILE_FIELDS}
        self._cursor_steps = None   # set when a new cursor is uploaded

    def _process(self, field, max_mb, label, convert):
        f = self.cleaned_data.get(field)
        if isinstance(f, UploadedFile):  # a new upload (not the existing file)
            mt.check_size(f, max_mb, label)
            return convert(f)
        return f

    def clean_avatar(self):
        return self._process(
            'avatar', settings.MAX_AVATAR_UPLOAD_MB, 'Profile pictures',
            lambda f: mt.make_thumbnail(f, settings.AVATAR_SIZE, animated=True),
        )

    def clean_banner(self):
        w, h = settings.BANNER_SIZE
        return self._process(
            'banner', settings.MAX_BANNER_UPLOAD_MB, 'Banners',
            lambda f: mt.fit_image(f, w, h, animated_size=settings.ANIMATED_BANNER_SIZE),
        )

    def clean_background_image(self):
        return self._process(
            'background_image', settings.MAX_BACKGROUND_UPLOAD_MB, 'Background images',
            lambda f: mt.compress_image(
                f, settings.BACKGROUND_MAX_SIDE,
                animated_max_side=settings.ANIMATED_BACKGROUND_MAX_SIDE),
        )

    def clean_cursor(self):
        f = self.cleaned_data.get('cursor')
        if isinstance(f, UploadedFile):  # a new upload: a picture, an animated picture or a .ani file
            mt.check_size(f, getattr(settings, 'MAX_CURSOR_UPLOAD_MB', 2), 'Cursors')
            cursor, self._cursor_steps = mt.make_cursor(f)
            return cursor
        return f

    def clean(self):
        data = super().clean()
        for flag, field in (('remove_banner', 'banner'),
                            ('remove_background_image', 'background_image'),
                            ('remove_cursor', 'cursor')):
            # A new upload wins over the "remove" checkbox.
            if data.get(flag) and not isinstance(data.get(field), ContentFile):
                data[field] = False  # False tells Django to clear the file
        return data

    def clean_background_color(self):
        return self.cleaned_data['background_color'].lower()

    def clean_card_color(self):
        return self.cleaned_data['card_color'].lower()

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self._cursor_steps is not None:      # a new cursor decides how it moves
            profile.cursor_steps = self._cursor_steps
        elif not profile.cursor:                # cursor removed: no animation either
            profile.cursor_steps = []
        if commit:
            profile.save()
            self.save_m2m()
            for name, old in self._old_files.items():
                if old and old != getattr(profile, name).name:
                    profile._meta.get_field(name).storage.delete(old)
        return profile


class SignupForm(UserCreationForm):
    """Username + password + a referral code. No code, no account."""
    referral_code = forms.CharField(
        label='Referral code', max_length=32,
        widget=forms.TextInput(attrs={
            'class': 'code-input', 'placeholder': 'XXXX-XXXX', 'autocomplete': 'off',
            'autocapitalize': 'characters', 'spellcheck': 'false', 'autofocus': True,
        }),
    )
    field_order = ['referral_code', 'username', 'password1', 'password2']

    class Meta(UserCreationForm.Meta):
        fields = ('username',)

    def clean_referral_code(self):
        raw = self.cleaned_data['referral_code'].strip().upper()
        code = ReferralCode.objects.filter(code=raw).first()
        # one message for "does not exist", "switched off" and "used up", so nobody can probe for codes
        if code is None or not code.is_usable:
            raise forms.ValidationError("That referral code isn't valid.")
        self.referral = code
        return raw


class SettingsForm(forms.ModelForm):
    """The settings page: the look of the site (theme) and who can see you without an account."""

    class Meta:
        model = Profile
        fields = ['theme', 'is_public', 'public_posts', 'public_tweets']
        widgets = {'theme': forms.RadioSelect}
        labels = {
            'is_public': 'Anyone can see my profile',
            'public_posts': 'Show my posts',
            'public_tweets': 'Show my tweets and comments',
        }
        help_texts = {
            'is_public': 'Off: people who are not signed in are sent to the login page. '
                         'Members always see your profile.',
            'public_posts': 'Posts, plus the pins and collections on your profile.',
            'public_tweets': 'Tweets and the comments you wrote.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['theme'].required = False
        self.fields['theme'].choices = Profile._meta.get_field('theme').choices   # no blank choice

    def clean_theme(self):
        return self.cleaned_data.get('theme') or self.instance.theme
