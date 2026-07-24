from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from common import structlog
from common.core.paths import get_tool_data_dir
from storage.models import (
    Base,
    Collection,
    CollectionMember,
    Document,
    IndexRun,
    SourceType,
    TreeNode,
)

logger = structlog.get_logger(__name__)

_RAG_TOOL = "rag"


def _get_db_path(profile: str | None = None) -> Path:
    return get_tool_data_dir(_RAG_TOOL, profile) / "rag.db"


def create_engine_for_rag(
    db_path: str | Path | None = None, profile: str | None = None
):
    if db_path is None:
        resolved = _get_db_path(profile)
    else:
        resolved = Path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite+pysqlite:///{resolved}"
    logger.info("rag_engine_created", path=str(resolved))
    eng = create_engine(
        url,
        future=True,
        echo=False,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_conn, _rec):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return eng


def create_memory_engine():
    from sqlalchemy.pool import StaticPool

    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_conn, _rec):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)
    return eng


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def _session_scope(session_factory):
    from contextlib import contextmanager

    @contextmanager
    def _scope():
        session: Session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return _scope()


class RagStore:
    def __init__(self, session_factory):
        self._sf = session_factory

    def _session(self):
        return _session_scope(self._sf)

    def ensure_tables(self, engine):
        Base.metadata.create_all(engine)
        self._migrate_missing_columns(engine)

    def _migrate_missing_columns(self, engine):
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())

        expected_columns = {
            "tree_nodes": {"text"},
        }

        for table_name, required_cols in expected_columns.items():
            if table_name not in existing_tables:
                continue
            existing = {col["name"] for col in inspector.get_columns(table_name)}
            missing = required_cols - existing
            if not missing:
                continue
            with engine.begin() as conn:
                for col_name in sorted(missing):
                    if table_name == "tree_nodes" and col_name == "text":
                        conn.execute(text("ALTER TABLE tree_nodes ADD COLUMN text TEXT NOT NULL DEFAULT ''"))
                        logger.info("schema_migration", table=table_name, column=col_name)

    # ── Collection CRUD ──────────────────────────────────────────────────────

    def create_collection(self, name: str, description: str = "") -> dict:
        with self._session() as s:
            existing = s.query(Collection).filter_by(name=name).first()
            if existing:
                raise ValueError(f"Collection {name!r} already exists")
            c = Collection(name=name, description=description)
            s.add(c)
            s.flush()
            logger.info("collection_created", name=name)
            return {"id": c.id, "name": c.name, "description": c.description}

    def list_collections(self) -> list[dict]:
        with self._session() as s:
            rows = s.query(Collection).order_by(Collection.name).all()
            return [{"id": c.id, "name": c.name, "description": c.description} for c in rows]

    def get_collection(self, name: str) -> Collection | None:
        with self._session() as s:
            return s.query(Collection).filter_by(name=name).first()

    def delete_collection(self, name: str) -> bool:
        with self._session() as s:
            c = s.query(Collection).filter_by(name=name).first()
            if not c:
                return False
            s.delete(c)
            logger.info("collection_deleted", name=name)
            return True

    def get_collection_members(self, collection_id: int) -> list[dict]:
        with self._session() as s:
            members = (
                s.query(CollectionMember, Document)
                .join(Document, CollectionMember.document_id == Document.id)
                .filter(CollectionMember.collection_id == collection_id)
                .all()
            )
            results = []
            for cm, doc in members:
                root_title = ""
                if cm.root_node_id:
                    root_node = s.get(TreeNode, cm.root_node_id)
                    if root_node:
                        root_title = root_node.title
                results.append(
                    {
                        "handle": doc.handle,
                        "title": doc.title,
                        "description": doc.description,
                        "source_type": doc.source_type.value,
                        "root_node_title": root_title,
                        "added_at": cm.added_at,
                    }
                )
            return results

    # ── Document CRUD ────────────────────────────────────────────────────────

    def get_document_by_handle(self, handle: str) -> Document | None:
        with self._session() as s:
            return s.query(Document).filter_by(handle=handle).first()

    def upsert_document(
        self,
        handle: str,
        source_type: SourceType,
        source_ref: str,
        content_hash: str,
        title: str = "",
        description: str = "",
    ) -> Document:
        with self._session() as s:
            doc = s.query(Document).filter_by(handle=handle).first()
            if doc:
                doc.content_hash = content_hash
                doc.title = title or doc.title
                doc.description = description or doc.description
                doc.source_ref = source_ref
                s.flush()
                logger.info("document_updated", handle=handle)
                return doc
            doc = Document(
                handle=handle,
                source_type=source_type,
                source_ref=source_ref,
                content_hash=content_hash,
                title=title,
                description=description,
            )
            s.add(doc)
            s.flush()
            logger.info("document_created", handle=handle)
            return doc

    def list_documents_in_collection(
        self, collection_id: int | None = None
    ) -> list[dict]:
        with self._session() as s:
            if collection_id is not None:
                rows = (
                    s.query(Document)
                    .join(CollectionMember, CollectionMember.document_id == Document.id)
                    .filter(CollectionMember.collection_id == collection_id)
                    .order_by(Document.title)
                    .all()
                )
            else:
                rows = s.query(Document).order_by(Document.title).all()
            return [
                {
                    "handle": d.handle,
                    "title": d.title,
                    "description": d.description,
                    "source_type": d.source_type.value,
                    "created_at": d.created_at,
                }
                for d in rows
            ]

    # ── TreeNode CRUD ────────────────────────────────────────────────────────

    def get_tree_nodes_for_document(self, document_id: int) -> list[TreeNode]:
        with self._session() as s:
            return (
                s.query(TreeNode)
                .filter_by(document_id=document_id)
                .order_by(TreeNode.order_index)
                .all()
            )

    def get_tree_node_by_node_id(
        self, document_id: int, node_id: str
    ) -> TreeNode | None:
        with self._session() as s:
            return (
                s.query(TreeNode)
                .filter_by(document_id=document_id, node_id=node_id)
                .first()
            )

    def get_children_of_node(self, node_id: int) -> list[TreeNode]:
        with self._session() as s:
            return (
                s.query(TreeNode)
                .filter_by(parent_id=node_id)
                .order_by(TreeNode.order_index)
                .all()
            )

    def persist_tree(
        self, document_id: int, tree: list[dict], tags_by_node: dict[str, list[str]] | None = None
    ) -> int:
        with self._session() as s:
            s.query(TreeNode).filter_by(document_id=document_id).delete()
            counter = [0]

            def _persist_nodes(nodes: list[dict], parent_id: int | None, order: int) -> int:
                for i, node in enumerate(nodes):
                    tn = TreeNode(
                        document_id=document_id,
                        node_id=node["node_id"],
                        parent_id=parent_id,
                        title=node.get("title", ""),
                        text=node.get("text", ""),
                        start_index=node.get("start_index", 0),
                        end_index=node.get("end_index", 0),
                        summary=node.get("summary", ""),
                        order_index=order + i,
                        tags=json.dumps(tags_by_node.get(node["node_id"])) if tags_by_node and node["node_id"] in tags_by_node else None,
                    )
                    s.add(tn)
                    s.flush()
                    counter[0] += 1
                    children = node.get("nodes", [])
                    if children:
                        _persist_nodes(children, parent_id=tn.id, order=order + i + 1)
                return counter[0]

            total = _persist_nodes(tree, parent_id=None, order=0)
            logger.info("tree_persisted", document_id=document_id, nodes=total)
            return total

    def get_root_nodes_for_collection(
        self, collection_id: int
    ) -> list[tuple[Document, TreeNode | None]]:
        with self._session() as s:
            members = (
                s.query(CollectionMember, Document)
                .join(Document, CollectionMember.document_id == Document.id)
                .filter(CollectionMember.collection_id == collection_id)
                .all()
            )
            results = []
            for cm, doc in members:
                if cm.root_node_id:
                    root_node = s.get(TreeNode, cm.root_node_id)
                else:
                    root_node = (
                        s.query(TreeNode)
                        .filter_by(document_id=doc.id, parent_id=None)
                        .order_by(TreeNode.order_index)
                        .first()
                    )
                results.append((doc, root_node))
            return results

    def get_reachable_node_ids(
        self, collection_id: int, document_id: int
    ) -> set[str]:
        with self._session() as s:
            member = (
                s.query(CollectionMember)
                .filter_by(
                    collection_id=collection_id, document_id=document_id
                )
                .first()
            )
            if not member:
                raise ValueError(
                    f"Document {document_id} not in collection {collection_id}"
                )

            if member.root_node_id is None:
                all_nodes = (
                    s.query(TreeNode.node_id)
                    .filter_by(document_id=document_id)
                    .all()
                )
                return {n[0] for n in all_nodes}

            descendant_ids: set[int] = set()
            queue = [member.root_node_id]
            while queue:
                current = queue.pop()
                descendant_ids.add(current)
                children = (
                    s.query(TreeNode.id)
                    .filter_by(parent_id=current)
                    .all()
                )
                queue.extend(c[0] for c in children)

            root_node = s.get(TreeNode, member.root_node_id)
            if root_node:
                descendant_ids.add(root_node.id)

            all_nodes = (
                s.query(TreeNode.node_id, TreeNode.id)
                .filter_by(document_id=document_id)
                .all()
            )
            return {nid for nid, tid in all_nodes if tid in descendant_ids}

    # ── IndexRun ─────────────────────────────────────────────────────────────

    def create_index_run(
        self, document_id: int, model_used: str = "", is_ephemeral: int = 0
    ) -> IndexRun:
        with self._session() as s:
            run = IndexRun(
                document_id=document_id,
                model_used=model_used,
                is_ephemeral=is_ephemeral,
            )
            s.add(run)
            s.flush()
            return run

    def finish_index_run(
        self, run_id: int, status: str, error: str | None = None
    ) -> None:
        from datetime import datetime, timezone

        with self._session() as s:
            run = s.get(IndexRun, run_id)
            if run:
                run.status = status
                run.finished_at = datetime.now(timezone.utc).isoformat()
                run.error = error

    # ── Add member ───────────────────────────────────────────────────────────

    def add_collection_member(
        self,
        collection_id: int,
        document_id: int,
        root_node_id: int | None = None,
    ) -> None:
        from datetime import datetime, timezone

        with self._session() as s:
            existing = (
                s.query(CollectionMember)
                .filter_by(
                    collection_id=collection_id,
                    document_id=document_id,
                    root_node_id=root_node_id,
                )
                .first()
            )
            if existing:
                return
            cm = CollectionMember(
                collection_id=collection_id,
                document_id=document_id,
                root_node_id=root_node_id,
                added_at=datetime.now(timezone.utc).isoformat(),
            )
            s.add(cm)
            logger.info(
                "collection_member_added",
                collection_id=collection_id,
                document_id=document_id,
                root_node_id=root_node_id,
            )

    def remove_collection_member(
        self,
        collection_id: int,
        document_id: int,
    ) -> bool:
        with self._session() as s:
            cm = (
                s.query(CollectionMember)
                .filter_by(collection_id=collection_id, document_id=document_id)
                .first()
            )
            if not cm:
                return False
            s.delete(cm)
            return True

    def purge_document(self, document_id: int) -> bool:
        with self._session() as s:
            doc = s.get(Document, document_id)
            if not doc:
                return False
            s.delete(doc)
            logger.info("document_purged", document_id=document_id)
            return True
