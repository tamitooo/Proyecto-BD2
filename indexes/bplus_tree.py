from bisect import bisect_left, bisect_right
from math import ceil


class BPlusNode:
    def __init__(self, is_leaf=False):
        self.is_leaf = is_leaf
        self.keys = []
        self.parent = None
        self.children = []
        self.values = []
        self.next = None
        self.prev = None


class BPlusTree:
    def __init__(self, order=4):
        if order < 3:
            raise ValueError("order must be >= 3")
        self.order = order
        self.root = BPlusNode(is_leaf=True)
        self._size = 0

    @property
    def max_keys(self):
        return self.order - 1

    @property
    def min_leaf_keys(self):
        return ceil(self.max_keys / 2)

    @property
    def min_internal_children(self):
        return ceil(self.order / 2)

    def __len__(self):
        return self._size

    def _first_key(self, node):
        while not node.is_leaf:
            node = node.children[0]
        return node.keys[0] if node.keys else None

    def _recompute_keys(self, node):
        if not node.is_leaf:
            node.keys = [self._first_key(child) for child in node.children[1:]]

    def _refresh_upwards(self, node):
        while node is not None:
            self._recompute_keys(node)
            node = node.parent

    def _find_leaf(self, key):
        node = self.root
        while not node.is_leaf:
            node = node.children[bisect_right(node.keys, key)]
        return node

    def search(self, key):
        leaf = self._find_leaf(key)
        idx = bisect_left(leaf.keys, key)
        if idx < len(leaf.keys) and leaf.keys[idx] == key:
            return list(leaf.values[idx])
        return []

    def insert(self, key, value):
        leaf = self._find_leaf(key)
        idx = bisect_left(leaf.keys, key)

        if idx < len(leaf.keys) and leaf.keys[idx] == key:
            leaf.values[idx].append(value)
            self._size += 1
            return

        leaf.keys.insert(idx, key)
        leaf.values.insert(idx, [value])
        self._size += 1

        if len(leaf.keys) > self.max_keys:
            self._split_leaf(leaf)
        else:
            self._refresh_upwards(leaf.parent)

    def _split_leaf(self, leaf):
        right = BPlusNode(is_leaf=True)
        split = (len(leaf.keys) + 1) // 2

        right.keys = leaf.keys[split:]
        right.values = leaf.values[split:]
        leaf.keys = leaf.keys[:split]
        leaf.values = leaf.values[:split]

        right.next = leaf.next
        if right.next is not None:
            right.next.prev = right
        leaf.next = right
        right.prev = leaf

        if leaf is self.root:
            new_root = BPlusNode(is_leaf=False)
            new_root.children = [leaf, right]
            leaf.parent = new_root
            right.parent = new_root
            self._recompute_keys(new_root)
            self.root = new_root
            return

        parent = leaf.parent
        right.parent = parent
        pos = parent.children.index(leaf)
        parent.children.insert(pos + 1, right)
        self._recompute_keys(parent)

        if len(parent.children) > self.order:
            self._split_internal(parent)
        else:
            self._refresh_upwards(parent.parent)

    def _split_internal(self, node):
        right = BPlusNode(is_leaf=False)
        split = (len(node.children) + 1) // 2

        right.children = node.children[split:]
        node.children = node.children[:split]

        for child in right.children:
            child.parent = right

        self._recompute_keys(node)
        self._recompute_keys(right)

        if node is self.root:
            new_root = BPlusNode(is_leaf=False)
            new_root.children = [node, right]
            node.parent = new_root
            right.parent = new_root
            self._recompute_keys(new_root)
            self.root = new_root
            return

        parent = node.parent
        right.parent = parent
        pos = parent.children.index(node)
        parent.children.insert(pos + 1, right)
        self._recompute_keys(parent)

        if len(parent.children) > self.order:
            self._split_internal(parent)
        else:
            self._refresh_upwards(parent.parent)

    def delete(self, key, value=None):
        leaf = self._find_leaf(key)
        idx = bisect_left(leaf.keys, key)

        if idx >= len(leaf.keys) or leaf.keys[idx] != key:
            return False

        values = leaf.values[idx]
        if value is not None:
            try:
                values.remove(value)
            except ValueError:
                return False
            self._size -= 1
            if values:
                return True
        else:
            self._size -= len(values)

        leaf.keys.pop(idx)
        leaf.values.pop(idx)

        if leaf is self.root:
            return True

        if len(leaf.keys) < self.min_leaf_keys:
            self._rebalance_leaf(leaf)
        else:
            self._refresh_upwards(leaf.parent)
        return True

    def _rebalance_leaf(self, leaf):
        parent = leaf.parent
        idx = parent.children.index(leaf)
        left = parent.children[idx - 1] if idx > 0 else None
        right = parent.children[idx + 1] if idx + 1 < len(parent.children) else None

        if left is not None and len(left.keys) > self.min_leaf_keys:
            leaf.keys.insert(0, left.keys.pop())
            leaf.values.insert(0, left.values.pop())
            self._refresh_upwards(parent)
            return

        if right is not None and len(right.keys) > self.min_leaf_keys:
            leaf.keys.append(right.keys.pop(0))
            leaf.values.append(right.values.pop(0))
            self._refresh_upwards(parent)
            return

        if left is not None:
            left.keys.extend(leaf.keys)
            left.values.extend(leaf.values)
            left.next = leaf.next
            if leaf.next is not None:
                leaf.next.prev = left
            parent.children.pop(idx)
            self._after_child_removed(parent)
            return

        if right is not None:
            leaf.keys.extend(right.keys)
            leaf.values.extend(right.values)
            leaf.next = right.next
            if right.next is not None:
                right.next.prev = leaf
            parent.children.pop(idx + 1)
            self._after_child_removed(parent)

    def _after_child_removed(self, node):
        self._recompute_keys(node)

        if node is self.root:
            if len(node.children) == 1:
                self.root = node.children[0]
                self.root.parent = None
            return

        if len(node.children) < self.min_internal_children:
            self._rebalance_internal(node)
        else:
            self._refresh_upwards(node.parent)

    def _rebalance_internal(self, node):
        parent = node.parent
        idx = parent.children.index(node)
        left = parent.children[idx - 1] if idx > 0 else None
        right = parent.children[idx + 1] if idx + 1 < len(parent.children) else None

        if left is not None and len(left.children) > self.min_internal_children:
            child = left.children.pop()
            child.parent = node
            node.children.insert(0, child)
            self._recompute_keys(left)
            self._recompute_keys(node)
            self._refresh_upwards(parent)
            return

        if right is not None and len(right.children) > self.min_internal_children:
            child = right.children.pop(0)
            child.parent = node
            node.children.append(child)
            self._recompute_keys(right)
            self._recompute_keys(node)
            self._refresh_upwards(parent)
            return

        if left is not None:
            for child in node.children:
                child.parent = left
            left.children.extend(node.children)
            self._recompute_keys(left)
            parent.children.pop(idx)
            self._after_child_removed(parent)
            return

        if right is not None:
            for child in right.children:
                child.parent = node
            node.children.extend(right.children)
            self._recompute_keys(node)
            parent.children.pop(idx + 1)
            self._after_child_removed(parent)

    def range_search(self, start=None, end=None, include_start=True, include_end=True, limit=None):
        if limit is not None and limit < 0:
            raise ValueError("limit must be >= 0")
        if limit == 0:
            return []

        if start is None:
            leaf = self.root
            while not leaf.is_leaf:
                leaf = leaf.children[0]
            idx = 0
        else:
            leaf = self._find_leaf(start)
            idx = bisect_left(leaf.keys, start) if include_start else bisect_right(leaf.keys, start)

        result = []
        while leaf is not None:
            while idx < len(leaf.keys):
                key = leaf.keys[idx]
                if end is not None and (key > end or (key == end and not include_end)):
                    return result

                for value in leaf.values[idx]:
                    result.append((key, value))
                    if limit is not None and len(result) >= limit:
                        return result
                idx += 1

            leaf = leaf.next
            idx = 0

        return result

    def validate(self):
        if self.root.parent is not None:
            raise AssertionError("root cannot have a parent")

        leaf_depths = set()
        leaves = []

        def walk(node, depth):
            if node.keys != sorted(node.keys):
                raise AssertionError("node keys are not sorted")

            if node.is_leaf:
                if len(node.keys) != len(node.values):
                    raise AssertionError("leaf key/value count mismatch")
                if node is not self.root and len(node.keys) < self.min_leaf_keys:
                    raise AssertionError("leaf underflow")
                if len(node.keys) > self.max_keys:
                    raise AssertionError("leaf overflow")
                leaf_depths.add(depth)
                leaves.append(node)
                return

            if len(node.children) != len(node.keys) + 1:
                raise AssertionError("internal key/child count mismatch")
            if node is not self.root and len(node.children) < self.min_internal_children:
                raise AssertionError("internal underflow")
            if len(node.children) > self.order:
                raise AssertionError("internal overflow")

            expected = [self._first_key(child) for child in node.children[1:]]
            if node.keys != expected:
                raise AssertionError("invalid separator keys")

            for child in node.children:
                if child.parent is not node:
                    raise AssertionError("invalid parent pointer")
                walk(child, depth + 1)

        walk(self.root, 0)

        if len(leaf_depths) > 1:
            raise AssertionError("leaves are at different depths")

        if leaves:
            current = leaves[0]
            previous = None
            linked_keys = []

            while current is not None:
                if current.prev is not previous:
                    raise AssertionError("invalid leaf prev link")
                linked_keys.extend(current.keys)
                previous = current
                current = current.next

            if linked_keys != sorted(linked_keys):
                raise AssertionError("leaf chain is not sorted")
            if len(linked_keys) != len(set(linked_keys)):
                raise AssertionError("duplicate keys stored as separate leaf entries")

        entry_count = sum(len(values) for leaf in leaves for values in leaf.values)
        if entry_count != self._size:
            raise AssertionError("tree size counter mismatch")

        return True
