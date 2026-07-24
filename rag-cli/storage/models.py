from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class SourceType(enum.Enum):
    local_file = "local_file"
    corpus = "corpus"


class IndexRunStatus(enum.Enum):
    running = "running"
    success = "success"
    failed = "failed"


class Collection(Base):
    __tablename__ = "collections"
    __table_args__ = (
        UniqueConstraint("name", name="uq_collections_name"),
        Index("ix_collections_name", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=_utcnow)

    members: Mapped[list["CollectionMember"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("handle", name="uq_documents_handle"),
        Index("ix_documents_handle", "handle"),
        Index("ix_documents_content_hash", "content_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    handle: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType), nullable=False
    )
    source_ref: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=_utcnow)
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default=_utcnow)

    tree_nodes: Mapped[list["TreeNode"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    index_runs: Mapped[list["IndexRun"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    collection_members: Mapped[list["CollectionMember"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class TreeNode(Base):
    __tablename__ = "tree_nodes"
    __table_args__ = (
        Index("ix_tree_nodes_document_id", "document_id"),
        Index("ix_tree_nodes_node_id", "node_id"),
        Index("ix_tree_nodes_parent_id", "parent_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(String, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("tree_nodes.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    start_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="tree_nodes")
    parent: Mapped["TreeNode | None"] = relationship(
        remote_side="TreeNode.id", back_populates="children"
    )
    children: Mapped[list["TreeNode"]] = relationship(back_populates="parent")


class CollectionMember(Base):
    __tablename__ = "collection_members"
    __table_args__ = (
        UniqueConstraint(
            "collection_id",
            "document_id",
            "root_node_id",
            name="uq_collection_member_scope",
        ),
        Index("ix_collection_members_collection_id", "collection_id"),
        Index("ix_collection_members_document_id", "document_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    root_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("tree_nodes.id", ondelete="SET NULL"), nullable=True
    )
    added_at: Mapped[str] = mapped_column(String, nullable=False, default=_utcnow)

    collection: Mapped["Collection"] = relationship(back_populates="members")
    document: Mapped["Document"] = relationship(back_populates="collection_members")


class IndexRun(Base):
    __tablename__ = "index_runs"
    __table_args__ = (
        Index("ix_index_runs_document_id", "document_id"),
        Index("ix_index_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    model_used: Mapped[str] = mapped_column(String, nullable=False, default="")
    started_at: Mapped[str] = mapped_column(String, nullable=False, default=_utcnow)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[IndexRunStatus] = mapped_column(
        Enum(IndexRunStatus), nullable=False, default=IndexRunStatus.running
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_ephemeral: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    document: Mapped["Document"] = relationship(back_populates="index_runs")
