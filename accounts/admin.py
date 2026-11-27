from django.contrib import admin

from .models import Follow, Profile, ReferralCode

admin.site.register(Profile)
admin.site.register(Follow)


@admin.register(ReferralCode)
class ReferralCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'note', 'used', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('code', 'note', 'profiles__user__username')
    fields = ('code', 'note', 'max_uses', 'is_active', 'uses', 'used_by', 'created_at')
    readonly_fields = ('uses', 'used_by', 'created_at')

    @admin.display(description='Used')
    def used(self, obj):
        return f'{obj.uses} / {obj.max_uses}'

    @admin.display(description='Signed up with it')
    def used_by(self, obj):
        if not obj.pk:
            return '-'
        names = [p.user.username for p in obj.profiles.select_related('user')]
        return ', '.join(names) or 'nobody yet'
