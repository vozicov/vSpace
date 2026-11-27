import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    """Step 3 of 3: drop the old group/grid columns now that the data has moved."""

    dependencies = [
        ('shelf', '0003_groups_to_folders'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='shelfitem', options={'ordering': ['position', 'id']}),
        migrations.RemoveField(model_name='shelfitem', name='group'),
        migrations.RemoveField(model_name='shelfitem', name='col'),
        migrations.RemoveField(model_name='shelfitem', name='row'),
        migrations.RemoveField(model_name='shelfitem', name='col_span'),
        migrations.RemoveField(model_name='shelfitem', name='row_span'),
        migrations.DeleteModel(name='ShelfGroup'),
        migrations.AlterField(
            model_name='shelfitem',
            name='owner',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='shelf_items', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddConstraint(
            model_name='shelfitem',
            constraint=models.UniqueConstraint(
                fields=('owner', 'entry'), condition=Q(('entry__isnull', False)),
                name='unique_shelf_entry'),
        ),
    ]
