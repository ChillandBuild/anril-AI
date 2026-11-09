"""Minimal in-memory stand-in for the supabase-py client, covering the query chain the
knowledge auto-sort services use: table().select/insert/update/delete, eq/neq/is_/in_,
order, limit, execute. Rows get sequential created_at values so "newest first"
ordering is deterministic, and deleting a knowledge_documents row cascades the way the
real foreign keys do."""
import itertools
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

_DEFAULTS = {
    "knowledge_documents": {
        "status": "processing", "rule_lines": [], "sorted_at": None, "sort_state": None,
        "source_text": None, "full_text": None, "campaign_tag_id": None,
        "storage_path": None, "error_message": None, "name": "doc.txt",
    },
    "knowledge_reviews": {
        "status": "pending", "origin": "upload", "base_version_id": None,
        "proposed_description": "", "proposed_facts": "", "proposed_rule_lines": [],
        "conflicts": [], "fact_disagreements": [], "unverified": [], "left_out": [],
        "left_out_rules": [], "truncated": False, "replaces_document_id": None, "created_by": None,
        "suggested_handover": "",
    },
    "knowledge_versions": {"document_id": None, "created_by": None, "content": ""},
}

# child table -> (column, on-delete behaviour) when a knowledge_documents row is deleted
_CASCADES = {
    "knowledge_chunks": ("document_id", "delete"),
    "knowledge_versions": ("document_id", "delete"),
    "knowledge_reviews": ("document_id", "delete"),
}
_SET_NULL = {"knowledge_reviews": "replaces_document_id"}


class FakeSupabase:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self._clock = itertools.count(1)
        self.storage = MagicMock()
        self.rpc_handlers: dict = {}

    def table(self, name: str) -> "_Query":
        return _Query(self, name)

    def rpc(self, name: str, params: dict):
        """Calls the python handler registered in self.rpc_handlers (a stand-in for a SQL function)."""
        handler = self.rpc_handlers[name]
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=handler(params)))

    def rows(self, name: str) -> list[dict]:
        return self.tables.setdefault(name, [])

    def add(self, _table: str, **row) -> dict:
        return _Query(self, _table).insert(row).execute().data[0]

    def _stamp(self) -> str:
        return f"2026-01-01T00:00:{next(self._clock):012d}"


class _Query:
    def __init__(self, db: FakeSupabase, name: str):
        self.db, self.name = db, name
        self.op, self.payload = "select", None
        self.filters: list = []
        self._order: list[tuple[str, bool]] = []
        self._nullsfirst: dict[str, bool] = {}
        self._limit: int | None = None
        self._offset = 0
        self._single = False
        self._negate = False

    def _add_filter(self, predicate, null_matches_neither: str | None = None):
        """Append a row predicate, inverted when `.not_` came just before (PostgREST `not.<op>`).
        `null_matches_neither` names a column for which, like Postgres, a NULL matches neither
        the positive nor the negated form."""
        if self._negate:
            self._negate = False
            col = null_matches_neither
            self.filters.append(lambda r, p=predicate: not (col and r.get(col) is None) and not p(r))
        else:
            self.filters.append(predicate)
        return self

    @property
    def not_(self):
        self._negate = True
        return self

    def contains(self, column, values):
        """Array column contains every one of `values` (PostgREST `cs`)."""
        wanted = set(values)
        return self._add_filter(
            lambda r: r.get(column) is not None and wanted <= set(r.get(column)), null_matches_neither=column,
        )

    def ov(self, column, values):
        """Array column shares at least one of `values` (PostgREST `ov`)."""
        wanted = set(values)
        return self._add_filter(
            lambda r: r.get(column) is not None and bool(wanted & set(r.get(column))), null_matches_neither=column,
        )

    def select(self, _columns: str = "*", count: str | None = None):
        self.op = "select"
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload: dict):
        self.op, self.payload = "update", payload
        return self

    def upsert(self, payload: dict | list[dict], on_conflict: str = "id", ignore_duplicates: bool = False):
        self.op, self.payload, self._conflict = "upsert", payload, [c.strip() for c in on_conflict.split(",")]
        self._ignore_duplicates = ignore_duplicates
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, column, value):
        return self._add_filter(lambda r: r.get(column) == value)

    def neq(self, column, value):
        if value == "{}":
            # PostgREST reads neq.{} on an array column as "not empty".
            return self._add_filter(lambda r: bool(r.get(column)))
        return self._add_filter(lambda r: r.get(column) != value)

    def is_(self, column, value):
        assert value == "null", "fake only supports is_(col, 'null')"
        # Through _add_filter so `.not_.is_(col, "null")` means IS NOT NULL, as in PostgREST.
        return self._add_filter(lambda r: r.get(column) is None)

    def lt(self, column, value):
        def compare(r, col=column, v=value):
            actual = r.get(col)
            if actual is None:
                return False
            # Numeric comparison when both are numbers (but not booleans)
            if isinstance(actual, (int, float)) and not isinstance(actual, bool) and isinstance(v, (int, float)) and not isinstance(v, bool):
                return actual < v
            return str(actual) < str(v)
        self.filters.append(compare)
        return self

    def gt(self, column, value):
        def compare(r, col=column, v=value):
            actual = r.get(col)
            if actual is None:
                return False
            if isinstance(actual, (int, float)) and not isinstance(actual, bool) and isinstance(v, (int, float)) and not isinstance(v, bool):
                return actual > v
            return str(actual) > str(v)
        self.filters.append(compare)
        return self

    def gte(self, column, value):
        def compare(r, col=column, v=value):
            actual = r.get(col)
            if actual is None:
                return False
            # Numeric comparison when both are numbers (but not booleans)
            if isinstance(actual, (int, float)) and not isinstance(actual, bool) and isinstance(v, (int, float)) and not isinstance(v, bool):
                return actual >= v
            return str(actual) >= str(v)
        self.filters.append(compare)
        return self

    def lte(self, column, value):
        def compare(r, col=column, v=value):
            actual = r.get(col)
            if actual is None:
                return False
            # Numeric comparison when both are numbers (but not booleans)
            if isinstance(actual, (int, float)) and not isinstance(actual, bool) and isinstance(v, (int, float)) and not isinstance(v, bool):
                return actual <= v
            return str(actual) <= str(v)
        self.filters.append(compare)
        return self

    def maybe_single(self):
        self._single = True
        return self

    def in_(self, column, values):
        allowed = set(values)
        return self._add_filter(lambda r: r.get(column) in allowed)

    def or_(self, filter_string: str):
        """Minimal PostgREST `or_` support: "col.op.val,col2.op2.val2", OR'd together.
        Mirrors real Postgres null semantics: `neq`/`eq` never match a NULL column --
        that's why a conditional update needs an explicit `is.null` clause alongside `neq`."""
        clauses = [part.split(".", 2) for part in filter_string.split(",")]

        def predicate(r, clauses=clauses):
            for column, op, value in clauses:
                actual = r.get(column)
                if op == "is":
                    if value == "null" and actual is None:
                        return True
                elif op == "neq":
                    if actual is not None and str(actual) != value:
                        return True
                elif op == "eq":
                    if actual is not None and str(actual) == value:
                        return True
                elif op == "lte":
                    if actual is not None and str(actual) <= value:
                        return True
                elif op == "lt":
                    if actual is not None and str(actual) < value:
                        return True
                else:
                    raise AssertionError(f"fake or_ doesn't support op {op!r}")
            return False

        self.filters.append(predicate)
        return self

    def order(self, column, desc: bool = False, nullsfirst: bool | None = None):
        self._order.append((column, desc))
        if nullsfirst is not None:
            self._nullsfirst[column] = nullsfirst
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def range(self, start: int, end: int):
        """Inclusive row window like PostgREST `range`."""
        self._offset, self._limit = start, end - start + 1
        return self

    def _matching(self) -> list[dict]:
        return [r for r in self.db.rows(self.name) if all(f(r) for f in self.filters)]

    def execute(self):
        if self.op == "insert":
            payloads = self.payload if isinstance(self.payload, list) else [self.payload]
            created = []
            for p in payloads:
                row = {**_DEFAULTS.get(self.name, {}), **p}
                row.setdefault("id", str(uuid.uuid4()))
                row.setdefault("created_at", self.db._stamp())
                self.db.rows(self.name).append(row)
                created.append(dict(row))
            return SimpleNamespace(data=created, count=len(created))

        if self.op == "upsert":
            payloads = self.payload if isinstance(self.payload, list) else [self.payload]
            written = []
            for p in payloads:
                existing = [r for r in self.db.rows(self.name) if all(r.get(c) == p.get(c) for c in self._conflict)]
                if existing and getattr(self, "_ignore_duplicates", False):
                    continue  # ON CONFLICT DO NOTHING: PostgREST returns no row for it
                if existing:
                    existing[0].update(p)
                    written.append(dict(existing[0]))
                    continue
                row = {**_DEFAULTS.get(self.name, {}), **p}
                row.setdefault("id", str(uuid.uuid4()))
                row.setdefault("created_at", self.db._stamp())
                self.db.rows(self.name).append(row)
                written.append(dict(row))
            return SimpleNamespace(data=written, count=len(written))

        matched = self._matching()
        if self.op == "update":
            for r in matched:
                r.update(self.payload)
            return SimpleNamespace(data=[dict(r) for r in matched], count=len(matched))

        if self.op == "delete":
            ids = {r["id"] for r in matched}
            self.db.tables[self.name] = [r for r in self.db.rows(self.name) if r not in matched]
            if self.name == "knowledge_documents":
                for child, (column, _) in _CASCADES.items():
                    self.db.tables[child] = [r for r in self.db.rows(child) if r.get(column) not in ids]
                for child, column in _SET_NULL.items():
                    for r in self.db.rows(child):
                        if r.get(column) in ids:
                            r[column] = None
            return SimpleNamespace(data=[dict(r) for r in matched], count=len(matched))

        rows = [dict(r) for r in matched]
        for column, desc in reversed(self._order):  # stable sorts, last key first
            nullsfirst = self._nullsfirst.get(column, desc)
            rows.sort(key=lambda r, c=column, n=nullsfirst, d=desc: (
                (r.get(c) is not None) if n != d else (r.get(c) is None), r.get(c) or ""), reverse=desc)
        total = len(rows)  # like PostgREST count=exact: the total before limit / range
        rows = rows[self._offset:]
        if self._limit is not None:
            rows = rows[: self._limit]
        if self._single:
            return SimpleNamespace(data=rows[0] if rows else None, count=total)
        return SimpleNamespace(data=rows, count=total)
