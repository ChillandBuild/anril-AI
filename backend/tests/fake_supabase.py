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

# Anril Agents knowledge base (migration 257): parent table -> [(child table, column)], ON DELETE CASCADE.
_KB_CASCADES = {
    "companion_kb_collections": [("companion_kb_chunks", "collection_id"),
                                 ("companion_kb_chunk_questions", "collection_id")],
    "companion_kb_documents": [("companion_kb_pages", "document_id"), ("companion_kb_chunks", "document_id"),
                               ("companion_kb_shortcuts", "document_id")],   # migration 260
    "companion_kb_chunks": [("companion_kb_chunk_questions", "chunk_id")],
}


def _kb_cascade(db: "FakeSupabase", table: str, ids: set) -> None:
    """Deletes the child rows of `ids` the way the real foreign keys do, all the way down."""
    for child, column in _KB_CASCADES.get(table, []):
        gone = {r["id"] for r in db.rows(child) if r.get(column) in ids}
        db.tables[child] = [r for r in db.rows(child) if r.get(column) not in ids]
        if gone:
            _kb_cascade(db, child, gone)


class FakeSupabase:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self._clock = itertools.count(1)
        self.storage = MagicMock()
        self.rpc_handlers: dict = {
            "claim_memory_pair": lambda p: _claim_memory_pair(self, p),
            "companion_day_context": lambda p: _companion_day_context(self, p),
            "companion_set_slot_fact": lambda p: _companion_set_slot_fact(self, p),
            "match_memory_chunks": lambda p: _match_memory_chunks(self, p),
            "match_companion_kb_chunks": lambda p: _match_companion_kb_chunks(self, p),
            "companion_kb_question_tenants": lambda p: _companion_kb_question_tenants(self, p),
        }

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


class FakeStorage:
    """In-memory stand-in for supabase.storage. Opt in with `db.storage = FakeStorage()` (the default
    stays a MagicMock, which older tests assert on). `files` is keyed by (bucket, path) so a test can
    check a file is there or gone. Set `fail_remove = True` to make every remove() raise."""

    def __init__(self):
        self.files: dict[tuple[str, str], bytes] = {}
        self.fail_remove = False

    def from_(self, bucket: str) -> "_FakeBucket":
        return _FakeBucket(self, bucket)


class _FakeBucket:
    def __init__(self, storage: FakeStorage, bucket: str):
        self.storage, self.bucket = storage, bucket

    def upload(self, path: str, file, file_options: dict | None = None):
        if not isinstance(file, (bytes, bytearray)):
            with open(file, "rb") as fh:
                file = fh.read()
        self.storage.files[(self.bucket, path)] = bytes(file)
        return SimpleNamespace(path=path)

    def download(self, path: str, options=None, query_params=None) -> bytes:
        try:
            return self.storage.files[(self.bucket, path)]
        except KeyError:
            raise Exception(f"storage: object not found: {path}") from None

    def remove(self, paths: list[str]) -> list[dict]:
        if self.storage.fail_remove:
            raise Exception("storage: remove failed")
        return [{"name": p} for p in paths if self.storage.files.pop((self.bucket, p), None) is not None]

    def list(self, path: str | None = None, options=None) -> list[dict]:
        prefix = f"{path.strip('/')}/" if path else ""
        return [{"name": p[len(prefix):], "metadata": {"size": len(data)}}
                for (bucket, p), data in sorted(self.storage.files.items())
                if bucket == self.bucket and p.startswith(prefix) and "/" not in p[len(prefix):]]

    def copy(self, from_path: str, to_path: str) -> dict:
        self.storage.files[(self.bucket, to_path)] = self.download(from_path)
        return {"Key": f"{self.bucket}/{to_path}"}

    def create_signed_upload_url(self, path: str, options=None) -> dict:
        url = f"https://fake.storage/object/upload/sign/{self.bucket}/{path}?token=fake-token"
        return {"signed_url": url, "signedUrl": url, "token": "fake-token", "path": path}

    def create_signed_url(self, path: str, expires_in: int, options=None) -> dict:
        url = f"https://fake.storage/object/sign/{self.bucket}/{path}?token=fake-token"
        return {"signedURL": url, "signedUrl": url}


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

    def delete(self, *, count=None, returning="representation"):
        self.op = "delete"
        self._minimal = returning == "minimal"     # like PostgREST: the count comes back, the rows do not
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

    def like(self, column, pattern: str):
        """PostgREST `like`: % is any run of characters, _ is one character (case-sensitive)."""
        import re
        regex = re.compile("^" + "".join(".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in pattern) + "$", re.S)
        return self._add_filter(lambda r: r.get(column) is not None and bool(regex.match(str(r.get(column)))),
                                null_matches_neither=column)

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
            if self.name == "companion_kb_collections" and any(
                    r.get("collection_id") in ids for r in self.db.rows("companion_kb_documents")):
                # companion_kb_documents.collection_id is ON DELETE RESTRICT.
                raise Exception('23503: update or delete on table "companion_kb_collections" violates foreign key')
            self.db.tables[self.name] = [r for r in self.db.rows(self.name) if r not in matched]
            if self.name in _KB_CASCADES:
                _kb_cascade(self.db, self.name, ids)
            if self.name == "companion_kb_collections":
                for r in self.db.rows("companions"):
                    if r.get("knowledge_collection_id") in ids:
                        r["knowledge_collection_id"] = None
            if self.name == "knowledge_documents":
                for child, (column, _) in _CASCADES.items():
                    self.db.tables[child] = [r for r in self.db.rows(child) if r.get(column) not in ids]
                for child, column in _SET_NULL.items():
                    for r in self.db.rows(child):
                        if r.get(column) in ids:
                            r[column] = None
            if getattr(self, "_minimal", False):
                return SimpleNamespace(data=[], count=len(matched))
            return SimpleNamespace(data=[dict(r) for r in matched], count=len(matched))

        rows = [dict(r) for r in matched]
        for column, desc in reversed(self._order):  # stable sorts, last key first
            nullsfirst = self._nullsfirst.get(column, desc)
            rows.sort(key=lambda r, c=column, n=nullsfirst, d=desc: (
                (r.get(c) is not None) if n != d else (r.get(c) is None),
                r.get(c) if r.get(c) is not None else ""), reverse=desc)
        total = len(rows)  # like PostgREST count=exact: the total before limit / range
        rows = rows[self._offset:]
        if self._limit is not None:
            rows = rows[: self._limit]
        if self._single:
            return SimpleNamespace(data=rows[0] if rows else None, count=total)
        return SimpleNamespace(data=rows, count=total)


# --- stand-ins for the companion memory SQL functions (migration 256) ------------------------------

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _claim_memory_pair(db: "FakeSupabase", p: dict) -> bool:
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    until = (now + timedelta(seconds=p["p_seconds"])).isoformat()
    rows = [r for r in db.rows("companion_memory_state")
            if r["companion_id"] == p["p_companion"] and r["end_user_id"] == p["p_end_user"]]
    if not rows:
        db.add("companion_memory_state", tenant_id=p["p_tenant"], companion_id=p["p_companion"],
               end_user_id=p["p_end_user"], busy_until=until, failures=0, last_message_at=None)
        return True
    row = rows[0]
    busy = row.get("busy_until")
    if row["tenant_id"] != p["p_tenant"] or (busy and datetime.fromisoformat(busy) >= now):
        return False
    row["busy_until"] = until
    return True


def _companion_day_context(db: "FakeSupabase", p: dict) -> dict:
    key = (p["p_tenant"], p["p_companion"], p["p_end_user"])
    state = next((r for r in db.rows("companion_memory_state")
                  if (r["tenant_id"], r["companion_id"], r["end_user_id"]) == key), {})
    diary = sorted((r for r in db.rows("companion_memory_diary")
                    if (r["tenant_id"], r["companion_id"], r["end_user_id"]) == key
                    and str(r["day"]) < p["p_before_day"]), key=lambda r: str(r["day"]), reverse=True)
    cleaning = any(r.get("forget_pending") is not None for r in db.rows("companion_memory_state")
                   if (r["tenant_id"], r["end_user_id"]) == (p["p_tenant"], p["p_end_user"]))   # migration 263
    return {"recap": state.get("today_recap"), "recap_day": state.get("recap_day"), "cleaning": cleaning,
            "diary": [{"day": r["day"], "text": r["text"]} for r in diary[:p["p_days"]]]}


def _companion_set_slot_fact(db: "FakeSupabase", p: dict) -> dict:
    """Migration 262: close the pair's active fact in the slot, insert the new one."""
    key = (p["p_tenant"], p["p_companion"], p["p_end_user"])
    closed = [r for r in db.rows("companion_memory_facts")
              if (r["tenant_id"], r["companion_id"], r["end_user_id"]) == key
              and r.get("slot") == p["p_slot"] and r.get("status") == "active"]
    for row in closed:
        row.update(status="closed", valid_to=p["p_closed_on"], updated_at=_now_iso())
    fact = db.add("companion_memory_facts", tenant_id=p["p_tenant"], companion_id=p["p_companion"],
                  end_user_id=p["p_end_user"], section=p["p_section"], text=p["p_text"],
                  valid_from=p["p_valid_from"], valid_to=None, status="active", slot=p["p_slot"],
                  quote=p["p_quote"], source_message_id=p["p_source"], updated_at=_now_iso())
    return {"fact": fact, "closed": [dict(r) for r in closed]}


def _vector(value):
    if value is None:
        return None
    if isinstance(value, str):
        return [float(x) for x in value.strip("[]").split(",") if x]
    return list(value)


def _cosine(a, b) -> float:
    num = sum(x * y for x, y in zip(a, b))
    den = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
    return num / den if den else 0.0


def _word_sim(query: str, text: str) -> float:
    """A rough stand-in for pg_trgm word_similarity: the share of query words found in the text."""
    words = [w for w in query.casefold().split() if len(w) > 2]
    hay = text.casefold()
    return sum(w in hay for w in words) / len(words) if words else 0.0


def _match_memory_chunks(db: "FakeSupabase", p: dict) -> list[dict]:
    mine = [r for r in db.rows("companion_memory_chunks")
            if r["tenant_id"] == p["p_tenant"] and r["end_user_id"] == p["p_end_user"]
            and r["companion_id"] in p["p_companions"]]
    out = []
    q = _vector(p.get("p_embedding"))
    if q is not None:
        scored = [(r, _cosine(q, _vector(r["embedding"]))) for r in mine if r.get("embedding") is not None]
        for r, score in sorted(scored, key=lambda t: -t[1])[:p["p_count"]]:
            out.append({**{k: r[k] for k in ("id", "companion_id", "kind", "day", "text")},
                        "source": "vector", "score": score})
    if p.get("p_query"):
        scored = [(r, _word_sim(p["p_query"], r["text"])) for r in mine]
        for r, score in sorted(scored, key=lambda t: -t[1])[:p["p_count"]]:
            if score > 0:
                out.append({**{k: r[k] for k in ("id", "companion_id", "kind", "day", "text")},
                            "source": "trigram", "score": score})
    return out


# --- stand-in for match_companion_kb_chunks (migration 258) ----------------------------------------

def _match_companion_kb_chunks(db: "FakeSupabase", p: dict) -> list[dict]:
    """Same scope as the SQL function (one business, one collection, one tier) and the same
    "source" lists, with simple scoring: shared words for "words", a key term inside the text for
    "trigram", cosine for the vector lists when both sides have numbers. One row per (passage, list)."""
    titles = {d["id"]: d.get("title") for d in db.rows("companion_kb_documents") if d["tenant_id"] == p["p_tenant"]}
    scope = [r for r in db.rows("companion_kb_chunks")
             if r["tenant_id"] == p["p_tenant"] and r["collection_id"] == p["p_collection"]
             and r["tier"] == p["p_tier"] and r["document_id"] in titles]
    out: list[dict] = []

    def emit(source: str, scored: list[tuple[dict, float]]) -> None:
        for r, score in sorted((t for t in scored if t[1] > 0), key=lambda t: -t[1])[:p["p_count"]]:
            out.append({"id": r["id"], "document_id": r["document_id"], "document_title": titles[r["document_id"]],
                        "tier": r["tier"], "heading_path": r.get("heading_path") or "", "text": r["text"],
                        "page_from": r["page_from"], "page_to": r["page_to"], "source": source, "score": score})

    for source, key in (("vector_en", "p_embedding_en"), ("vector_ta", "p_embedding_ta")):
        q = _vector(p.get(key))
        if q is not None:
            emit(source, [(r, _cosine(q, _vector(r["embedding"]))) for r in scope
                          if r.get("embedding") is not None and r.get("embedding_model") == p["p_model"]])
    query = f"{p.get('p_query_en') or ''} {p.get('p_query_ta') or ''}"
    emit("words", [(r, _word_sim(query, r["text"])) for r in scope])
    terms = [t.casefold() for t in p.get("p_terms") or [] if len(t.strip()) >= 3]
    emit("trigram", [(r, 1.0 if any(t in r["text"].casefold() for t in terms) else 0.0) for r in scope])
    if p["p_tier"] == 1:
        ids = {r["id"]: r for r in scope}
        best: dict[str, float] = {}
        for cq in db.rows("companion_kb_chunk_questions"):
            if (cq["tenant_id"] != p["p_tenant"] or cq.get("chunk_id") not in ids or cq.get("embedding") is None
                    or cq.get("embedding_model") != p["p_model"]):
                continue
            for key in ("p_embedding_en", "p_embedding_ta"):
                q = _vector(p.get(key))
                if q is not None:
                    best[cq["chunk_id"]] = max(best.get(cq["chunk_id"], 0.0), _cosine(q, _vector(cq["embedding"])))
        emit("question", [(ids[i], score) for i, score in best.items()])
    return out


# --- stand-in for companion_kb_question_tenants (migration 260) ------------------------------------

def _companion_kb_question_tenants(db: "FakeSupabase", _p: dict) -> list[dict]:
    """SELECT DISTINCT tenant_id FROM companion_kb_question_log."""
    return [{"tenant_id": t} for t in sorted({r["tenant_id"] for r in db.rows("companion_kb_question_log")})]
