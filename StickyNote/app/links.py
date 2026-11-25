"""Which notes (and the calendar) are linked into groups that move together (rule M2).

Pure module: no tkinter. Every pair handed out is a sorted tuple ``(a, b)`` with ``a < b``.
"""
from geom import CAL, touching

__all__ = ["CAL", "Links", "links_from_touching"]


def _pair(a, b):
    return (a, b) if a < b else (b, a)


class Links:
    def __init__(self, pairs=()):
        self._adj: dict[str, set[str]] = {}
        for a, b in pairs:
            self.add(a, b)

    def add(self, a, b):
        if a == b:
            return
        self._adj.setdefault(a, set()).add(b)
        self._adj.setdefault(b, set()).add(a)

    def remove(self, a, b):
        for x, y in ((a, b), (b, a)):
            s = self._adj.get(x)
            if s is not None:
                s.discard(y)
                if not s:
                    del self._adj[x]

    def drop(self, id):
        for other in self._adj.pop(id, set()):
            self.remove(other, id)

    def linked(self, a, b) -> bool:
        return b in self._adj.get(a, ())

    def neighbours(self, id) -> set:
        return set(self._adj.get(id, ()))

    def group(self, id) -> set:
        seen, todo = {id}, [id]
        while todo:
            for n in self._adj.get(todo.pop(), ()):
                if n not in seen:
                    seen.add(n)
                    todo.append(n)
        return seen

    def pairs(self) -> set:
        return {_pair(a, b) for a, s in self._adj.items() for b in s}

    def prune_apart(self, parts, reach, slack) -> list:
        """Remove pairs whose parts don't touch and return them. A pair with either id
        missing from ``parts`` (minimized or closing note) is skipped and kept."""
        gone = []
        for a, b in sorted(self.pairs()):
            if a not in parts or b not in parts:
                continue
            if not any(touching(p, q, reach, slack) for p in parts[a] for q in parts[b]):
                gone.append((a, b))
        for a, b in gone:
            self.remove(a, b)
        return gone

    def to_lists(self) -> dict:
        return {a: sorted(s) for a, s in sorted(self._adj.items())}

    @classmethod
    def from_lists(cls, d, known):
        L = cls()
        if not isinstance(d, dict):
            return L
        for a, bs in d.items():
            if not isinstance(a, str) or a not in known or not isinstance(bs, (list, tuple)):
                continue
            for b in bs:
                if isinstance(b, str) and b in known:
                    L.add(a, b)
        return L


def links_from_touching(parts, reach, slack) -> Links:
    L = Links()
    ids = sorted(parts)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if any(touching(p, q, reach, slack) for p in parts[a] for q in parts[b]):
                L.add(a, b)
    return L
