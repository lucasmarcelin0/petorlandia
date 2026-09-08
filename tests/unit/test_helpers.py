import pytest
from helpers import unique_items_by_id


class DummyItem:
    def __init__(self, item_id=None, name=""):
        if item_id is not None:
            self.id = item_id
        self.name = name

    def __repr__(self):
        return f"DummyItem(id={getattr(self, 'id', None)}, name={self.name})"


def test_unique_items_by_id_empty():
    assert unique_items_by_id(None) == []
    assert unique_items_by_id([]) == []


def test_unique_items_by_id_unique_elements():
    item1 = DummyItem(1)
    item2 = DummyItem(2)
    item3 = DummyItem(3)
    items = [item1, item2, item3]
    result = unique_items_by_id(items)
    assert result == [item1, item2, item3]


def test_unique_items_by_id_with_duplicates():
    item1 = DummyItem(1, "first")
    item2 = DummyItem(2, "second")
    item1_dup = DummyItem(1, "duplicate")
    item3 = DummyItem(3, "third")
    items = [item1, item1_dup, item2, item3, item1_dup]

    result = unique_items_by_id(items)
    assert result == [item1, item2, item3]


def test_unique_items_by_id_missing_or_none_id():
    class ItemWithNoneId:
        def __init__(self):
            self.id = None

    item1 = DummyItem(1)
    item_no_id = DummyItem(name="no id")
    item_none_id = ItemWithNoneId()
    item2 = DummyItem(2)

    items = [item1, item_no_id, item_none_id, item2]
    result = unique_items_by_id(items)

    assert result == [item1, item2]


def test_unique_items_by_id_dictionaries():
    item1 = DummyItem(1)
    dict_item = {'id': 1}
    dict_item2 = {'id': 2}
    item2 = DummyItem(2)

    items = [item1, dict_item, dict_item2, item2]
    result = unique_items_by_id(items)

    assert result == [item1, item2]
