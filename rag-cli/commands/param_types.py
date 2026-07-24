from __future__ import annotations

import click


class CollectionNameType(click.ParamType):
    name = "collection_name"

    def shell_complete(self, ctx, param, incomplete):
        from commands.helpers import get_rag_store
        try:
            store, _ = get_rag_store()
            collections = store.list_collections()
            return [
                click.shell_completion.CompletionItem(c["name"])
                for c in collections
                if c["name"].startswith(incomplete)
            ]
        except Exception:
            return []


class DocumentHandleType(click.ParamType):
    name = "document_handle"

    def shell_complete(self, ctx, param, incomplete):
        from commands.helpers import get_rag_store
        try:
            store, _ = get_rag_store()
            docs = store.list_documents_in_collection()
            return [
                click.shell_completion.CompletionItem(d["handle"])
                for d in docs
                if d["handle"].startswith(incomplete)
            ]
        except Exception:
            return []


COLLECTION_NAME = CollectionNameType()
DOCUMENT_HANDLE = DocumentHandleType()
