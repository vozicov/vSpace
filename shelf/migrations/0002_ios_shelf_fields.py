import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Step 1 of 3: add the new columns next to the old ones (nothing is removed yet)."""

    dependencies = [
        ('feed', '0002_alter_entry_options_entry_media_entry_media_type_and_more'),
        ('shelf', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='shelfitem',
            name='owner',
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name='shelf_items', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='shelfitem',
            name='parent',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name='children', to='shelf.shelfitem'),
        ),
        migrations.AddField(
            model_name='shelfitem',
            name='position',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='shelfitem',
            name='size',
            field=models.CharField(
                choices=[('s', 'Small'), ('w', 'Wide'), ('l', 'Large')],
                default='s', max_length=1),
        ),
        migrations.AddField(
            model_name='shelfitem',
            name='rotation',
            field=models.SmallIntegerField(
                default=0, help_text='Tilt in degrees, -15 to 15.',
                validators=[django.core.validators.MinValueValidator(-15),
                            django.core.validators.MaxValueValidator(15)]),
        ),
        migrations.AlterField(
            model_name='shelfitem',
            name='kind',
            field=models.CharField(
                choices=[('image', 'Image or GIF'), ('music', 'Music'), ('post', 'Post'),
                         ('link', 'Link'), ('folder', 'Folder')],
                max_length=6),
        ),
        migrations.CreateModel(
            name='InterestPin',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slot', models.PositiveSmallIntegerField(
                    validators=[django.core.validators.MinValueValidator(1),
                                django.core.validators.MaxValueValidator(4)])),
                ('rotation', models.SmallIntegerField(default=0)),
                ('entry', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='pins', to='feed.entry')),
                ('owner', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='interest_pins', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['slot']},
        ),
        migrations.AddConstraint(
            model_name='interestpin',
            constraint=models.UniqueConstraint(
                fields=('owner', 'slot'), name='unique_pin_slot'),
        ),
        migrations.AddConstraint(
            model_name='interestpin',
            constraint=models.UniqueConstraint(
                fields=('owner', 'entry'), name='unique_pin_entry'),
        ),
        migrations.AddConstraint(
            model_name='interestpin',
            constraint=models.CheckConstraint(
                condition=models.Q(('slot__gte', 1), ('slot__lte', 4)),
                name='pin_slot_range'),
        ),
    ]
