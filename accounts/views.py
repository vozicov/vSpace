from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from shelf.models import ShelfItem

from .forms import ProfileForm, SettingsForm, SignupForm
from .models import Follow, Profile, ReferralCode

# Quick-pick colors under the color buttons on the edit page (any color can still be picked)
PALETTE = ['#faf6f0', '#ffffff', '#f3ece1', '#e7dccb', '#d9e4d3', '#6d4c41', '#2b2118', '#080603']


@login_required
@require_POST
def follow_toggle(request, username):
    target = get_object_or_404(get_user_model(), username=username)
    if target != request.user:
        link, created = Follow.objects.get_or_create(follower=request.user, following=target)
        if not created:
            link.delete()
    return redirect('profile', username=username)


@login_required
def profile_edit(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    is_post = request.method == 'POST'
    form = ProfileForm(
        request.POST if is_post else None,
        request.FILES if is_post else None,
        instance=profile,
    )
    if is_post and form.is_valid():
        form.save()
        return redirect('profile', username=request.user.username)

    me = request.user
    # A clean copy from the database. After a failed save `profile` holds unsaved values,
    # and the preview must start from what is really published.
    saved = Profile.objects.get(pk=profile.pk)
    return render(request, 'accounts/profile_edit.html', {
        'form': form,
        'saved': saved,
        'urls': {
            'avatar': saved.avatar.url if saved.avatar else '',
            'banner': saved.banner.url if saved.banner else '',
            'background': saved.background_image.url if saved.background_image else '',
            'cursor': saved.cursor.url if saved.cursor else '',
            # the picker tile cannot show a strip of frames, so an animated cursor gets no thumbnail
            'cursor_tile': '' if saved.cursor_animated else (saved.cursor.url if saved.cursor else ''),
        },
        'palette': PALETTE,
        'limits': {
            'avatar': settings.MAX_AVATAR_UPLOAD_MB,
            'banner': settings.MAX_BANNER_UPLOAD_MB,
            'background': settings.MAX_BACKGROUND_UPLOAD_MB,
            'cursor': getattr(settings, 'MAX_CURSOR_UPLOAD_MB', 2),
        },
        'followers_count': Follow.objects.filter(following=me).count(),
        'following_count': Follow.objects.filter(follower=me).count(),
        'collections_count': ShelfItem.objects.filter(
            owner=me, parent__isnull=True, kind=ShelfItem.Kind.FOLDER).count(),
    })


@login_required
def settings_page(request):
    """Settings: how the site looks around you (theme) and who may see your profile without signing in."""
    profile, _ = Profile.objects.get_or_create(user=request.user)
    is_post = request.method == 'POST'
    form = SettingsForm(request.POST if is_post else None, instance=profile)
    if is_post and form.is_valid():
        form.save()
        messages.success(request, 'Settings saved.')
        return redirect('settings')
    return render(request, 'accounts/settings.html', {'form': form})


def signup(request):
    if request.user.is_authenticated:
        return redirect('home')
    form = SignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            # Take one use of the code in a single database step. Two people sending the same
            # last-use code at the same moment cannot both get it: only one UPDATE matches.
            claimed = ReferralCode.objects.filter(
                pk=form.referral.pk, is_active=True, uses__lt=F('max_uses'),
            ).update(uses=F('uses') + 1)
            if claimed:
                user = form.save()
                Profile.objects.filter(user=user).update(referral_code=form.referral)
        if claimed:
            login(request, user)
            return redirect('profile_edit')   # new accounts start by setting up their page
        form.add_error('referral_code', "That referral code isn't valid.")
    return render(request, 'registration/signup.html', {'form': form})
