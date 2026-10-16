"""Trees: a table whose records have a parent in the same table (``Table.tree_field``).

Any table can be one (organisation, projects, locations, categories, ...), and
records of other tables link to its nodes as freely as to any record. Within a
tree, parent links never go round in a circle (checked by core.service).
"""
from collections import defaultdict

from django.core.exceptions import ValidationError

from .models import Field, Link


def parent_pairs(table):
    """{child id: parent id} for every record of the tree ``table`` that has a parent."""
    field = table.tree_field
    if field is None:
        return {}
    owner = field if field.opt('owner', True) else Field.objects.filter(pk=field.opt('inverse')).first()
    backwards = owner is not None and owner.pk != field.pk
    out = {}
    for src, dst in Link.objects.filter(field=owner).values_list('source_id', 'target_id'):
        child, parent = (dst, src) if backwards else (src, dst)
        out.setdefault(child, parent)
    return out


def would_cycle(table, record_id, parent_ids):
    """Whether making ``parent_ids`` the parents of ``record_id`` puts it under itself."""
    parents = parent_pairs(table)
    for start in parent_ids:
        node, seen = start, set()
        while node is not None and node not in seen:
            if node == record_id:
                return True
            seen.add(node)
            node = parents.get(node)
    return False


class Tree:
    """A tree table as the reader sees it (hidden records and what's only under them aren't there)."""

    def __init__(self, data, table):
        self.data, self.table = data, data.table(table)
        self.field = data.field(self.table.tree_field_id) if self.table and self.table.tree_field_id else None
        self.records = {r.pk: r for r in data.records(self.table)} if self.field else {}
        self.parent = {}
        self.children = defaultdict(list)
        for r in self.records.values():
            ids = [i for i in data.linked_ids(r, self.field) if i in self.records]
            if ids:
                self.parent[r.pk] = ids[0]
                self.children[ids[0]].append(r.pk)

    def ancestors(self, record_id):
        """From the top down to ``record_id``'s parent."""
        out, node, seen = [], self.parent.get(record_id), {record_id}
        while node is not None and node not in seen:
            seen.add(node)
            out.append(self.records[node])
            node = self.parent.get(node)
        return list(reversed(out))

    def kids(self, record_id):
        return [self.records[i] for i in self.children.get(record_id, [])]

    def descendant_ids(self, record_id):
        out, todo = set(), [record_id]
        while todo:
            for child in self.children.get(todo.pop(), []):
                if child not in out:
                    out.add(child)
                    todo.append(child)
        return out

    def roots(self):
        return [r for pk, r in self.records.items() if pk not in self.parent]


def make_tree(table, field):
    """Make ``table`` a tree with ``field`` (a link to the same table) as each record's parent."""
    if field is not None and (field.type != 'link' or field.table_id != table.pk or field.opt('target') != table.pk):
        raise ValidationError('A tree\'s parent is a link from the table to itself.')
    if field is not None and field.opt('multiple'):
        raise ValidationError(f'{field.name} links to many records; a tree needs one parent per record.')
    if field is not None:
        parents = defaultdict(list)
        owner_backwards = not field.opt('owner', True)
        owner_id = field.opt('inverse') if owner_backwards else field.pk
        for src, dst in Link.objects.filter(field_id=owner_id).values_list('source_id', 'target_id'):
            child, parent = (dst, src) if owner_backwards else (src, dst)
            parents[child].append(parent)
        for child in parents:
            node, seen = child, set()
            while node in parents and node not in seen:
                seen.add(node)
                node = parents[node][0]
                if node == child:
                    raise ValidationError(f'Some records of {table.name} are under themselves through {field.name}.')
    table.tree_field = field
    if field is None:
        table.is_space = False
    table.save(update_fields=['tree_field', 'is_space'])
    from .access import refresh_tables
    refresh_tables([table.pk])
