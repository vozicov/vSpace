from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_profile_cursor_steps'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='is_public',
            field=models.BooleanField(default=False, help_text='People who are not signed in can open this profile.'),
        ),
        migrations.AddField(
            model_name='profile',
            name='public_posts',
            field=models.BooleanField(default=True, help_text='...and see its posts (also pins and collections).'),
        ),
        migrations.AddField(
            model_name='profile',
            name='public_tweets',
            field=models.BooleanField(default=True, help_text='...and see its tweets and comments.'),
        ),
    ]
