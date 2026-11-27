from django.db import migrations


def groups_to_folders(apps, schema_editor):
    """Step 2 of 3: every old group becomes a folder and its items move inside it.

    Notes no longer exist, so they are deleted. A post can now be on a shelf only
    once, so if one owner pinned the same post twice, only the first copy is kept.
    """
    ShelfGroup = apps.get_model('shelf', 'ShelfGroup')
    ShelfItem = apps.get_model('shelf', 'ShelfItem')

    ShelfItem.objects.filter(kind='note').delete()

    next_position = {}   # owner id -> next free top-level position
    for group in ShelfGroup.objects.order_by('position', 'id'):
        position = next_position.get(group.owner_id, 0)
        next_position[group.owner_id] = position + 1

        # `group` is still a required column at this step, so the folder points at itself
        folder = ShelfItem.objects.create(
            owner_id=group.owner_id, group=group, kind='folder',
            title=group.title, position=position)

        items = (ShelfItem.objects.filter(group=group).exclude(pk=folder.pk)
                 .order_by('row', 'col', 'id'))
        for i, item in enumerate(items):
            item.owner_id = group.owner_id
            item.parent_id = folder.pk
            item.position = i
            if item.col_span > 1 and item.row_span > 1:
                item.size = 'l'
            elif item.col_span > 1:
                item.size = 'w'
            item.save()

    seen = set()
    for item in ShelfItem.objects.filter(entry__isnull=False).order_by('id'):
        key = (item.owner_id, item.entry_id)
        if key in seen:
            item.delete()
        seen.add(key)


class Migration(migrations.Migration):

    dependencies = [('shelf', '0002_ios_shelf_fields')]

    operations = [
        migrations.RunPython(groups_to_folders, migrations.RunPython.noop),
    ]
