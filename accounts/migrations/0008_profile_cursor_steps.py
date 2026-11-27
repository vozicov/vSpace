from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_profile_cursor'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='cursor_steps',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
