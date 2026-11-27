from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_profile_privacy'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='theme',
            field=models.CharField(choices=[('light', 'Light'), ('dark', 'Dark'), ('system', 'Same as my device')], default='light', max_length=6),
        ),
    ]
