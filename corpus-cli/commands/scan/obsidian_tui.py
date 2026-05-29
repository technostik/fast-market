"""Interactive Textual TUI for selecting Obsidian notes to add to the sync pool."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.widgets import Footer, Header, Input, Label, Markdown, Tree
from textual import on

if TYPE_CHECKING:
    from storage.sqlalchemy_store import SQLAlchemyStore

_SYSTEM_DIRS = {".obsidian", ".trash", ".git"}

_STATUS_NEW      = "new"
_STATUS_PENDING  = "pending"
_STATUS_SYNCED   = "synced"
_STATUS_EXCLUDED = "excluded"

_PREVIEW_MAX_CHARS = 10_000


@dataclass
class NodeData:
    rel_path: str    # vault-relative POSIX path; "" for vault root
    is_dir: bool
    abs_path: Path


@dataclass
class DirStats:
    new: int = 0
    pending: int = 0
    synced: int = 0
    excluded: int = 0

    @property
    def total(self) -> int:
        return self.new + self.pending + self.synced + self.excluded

    @property
    def actionable(self) -> int:
        return self.new + self.pending


class ObsidianScanApp(App[None]):
    """Navigate the Obsidian vault and add/remove/exclude files from the sync pool."""

    CSS = """
    #search-row {
        height: 3;
        border-bottom: solid $panel-darken-2;
        padding: 0 1;
    }
    #search-mode-label {
        width: 13;
        content-align: center middle;
        padding: 0 1;
        margin-right: 1;
        color: $accent;
    }
    #search-input {
        width: 1fr;
    }
    #tree-pane {
        width: 40%;
        border-right: solid $panel-darken-2;
        scrollbar-gutter: stable;
    }
    #preview-pane {
        width: 60%;
        padding: 1 2;
        overflow-y: auto;
    }
    """

    BINDINGS = [
        Binding("i", "include",      "Include",  show=True),
        Binding("r", "remove",       "Remove",   show=True),
        Binding("x", "exclude",      "Exclude",  show=True),
        Binding("c", "clean",        "Clean",    show=True),
        Binding("/", "focus_search", "Search",   show=True),
        Binding("f", "toggle_view",  "Full/New", show=True),
        Binding("q", "quit",         "Quit",     show=True),
    ]

    def __init__(
        self,
        vault: Path,
        status_map: dict[str, str],
        store: SQLAlchemyStore,
        extra_exclude_dirs: set[str] | None = None,
    ) -> None:
        super().__init__()
        self.vault = vault
        self._status_map = status_map
        self.store = store
        self._exclude_dirs: set[str] = _SYSTEM_DIRS | (extra_exclude_dirs or set())
        self._full_view = False
        self._current_node: NodeData | None = None
        self._dir_stats_cache: dict[str, DirStats] = {}
        self._search_text: str = ""
        self._search_mode: str = "title"  # "title" | "content"
        self._search_timer = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="search-row"):
            yield Label("[ Title ]", id="search-mode-label")
            yield Input(
                placeholder="/ to search  ·  Tab: title/content  ·  Esc: clear",
                id="search-input",
            )
        with Horizontal():
            yield Tree(
                Text.from_markup(f"[bold]📁 {self.vault.name}/[/]"),
                data=NodeData("", True, self.vault),
                id="tree-pane",
            )
            yield Markdown("", id="preview-pane")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Corpus Scan — Obsidian"
        self._refresh_tree()

    # ── Search ───────────────────────────────────────────────────────────────

    def action_focus_search(self) -> None:
        self.query_one("#search-input", Input).focus()

    def _toggle_search_mode(self) -> None:
        self._search_mode = "content" if self._search_mode == "title" else "title"
        label = self.query_one("#search-mode-label", Label)
        if self._search_mode == "content":
            label.update("[Content]")
        else:
            label.update("[ Title ]")
        self._refresh_tree()

    def on_key(self, event: Key) -> None:
        search_input = self.query_one("#search-input", Input)
        if not search_input.has_focus:
            return
        if event.key == "tab":
            event.prevent_default()
            self._toggle_search_mode()
        elif event.key == "escape":
            search_input.clear()
            self.set_focus(self.query_one("#tree-pane", Tree))

    @on(Input.Changed, "#search-input")
    def _on_search_changed(self, event: Input.Changed) -> None:
        self._search_text = event.value
        if self._search_timer is not None:
            self._search_timer.stop()
        self._search_timer = self.set_timer(0.25, self._refresh_tree)

    def _matching_paths(self) -> set[str] | None:
        """Returns matching rel paths for current search query, or None if search is empty."""
        query = _normalize(self._search_text)
        if not query:
            return None
        matches: set[str] = set()
        for f in self.vault.rglob("*.md"):
            rel_parts = f.relative_to(self.vault).parts
            if any(part in self._exclude_dirs for part in rel_parts[:-1]):
                continue
            rel = f.relative_to(self.vault).as_posix()
            if self._search_mode == "title":
                if query in _normalize(f.stem):
                    matches.add(rel)
            else:
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    if query in _normalize(content):
                        matches.add(rel)
                except Exception:
                    pass
        return matches

    # ── Tree construction ────────────────────────────────────────────────────

    def _refresh_tree(self) -> None:
        self._dir_stats_cache = self._compute_all_stats()
        matching = self._matching_paths()
        tree = self.query_one("#tree-pane", Tree)

        # Snapshot expanded dirs before tearing down so we can restore them.
        previously_expanded = _collect_expanded(tree.root)

        for child in list(tree.root.children):
            child.remove()
        self._populate_dir(tree.root, self.vault, "", matching)
        tree.root.expand()

        if matching is None:
            # Normal mode: restore user's open dirs.
            _restore_expanded(tree.root, previously_expanded)
        # Search mode: _populate_dir already expanded all matching dirs.

        self._update_subtitle()
        self._update_preview(self._current_node)

    def _compute_all_stats(self) -> dict[str, DirStats]:
        stats: dict[str, DirStats] = {"": DirStats()}
        seen: set[str] = set()
        for f in self.vault.rglob("*.md"):
            rel_parts = f.relative_to(self.vault).parts
            if any(part in self._exclude_dirs for part in rel_parts[:-1]):
                continue
            source_id = f.relative_to(self.vault).as_posix()
            seen.add(source_id)
            status = self._status_map.get(source_id, _STATUS_NEW)
            current_rel = ""
            _inc(stats, current_rel, status)
            for part in rel_parts[:-1]:
                current_rel = (current_rel + "/" + part).lstrip("/")
                _inc(stats, current_rel, status)
        # Orphaned: tracked in status_map but no longer on disk — count at root only.
        for source_id, status in self._status_map.items():
            if source_id not in seen:
                _inc(stats, "", status)
        return stats

    def _populate_dir(
        self,
        node,
        directory: Path,
        dir_rel: str,
        matching: set[str] | None = None,
    ) -> bool:
        has_visible = False
        try:
            entries = sorted(
                directory.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except PermissionError:
            return False

        for entry in entries:
            if entry.name in self._exclude_dirs:
                continue
            child_rel = (dir_rel + "/" + entry.name).lstrip("/")

            if entry.is_dir():
                s = self._dir_stats_cache.get(child_rel, DirStats())
                if s.total == 0:
                    continue
                # When searching, skip the actionable filter — show all dirs with matches.
                if matching is None and not self._full_view and s.actionable == 0:
                    continue
                label = _dir_label(entry.name, s, self._full_view)
                child = node.add(label, data=NodeData(child_rel, True, entry))
                if not self._populate_dir(child, entry, child_rel, matching):
                    child.remove()
                else:
                    has_visible = True
                    if matching is not None:
                        child.expand()

            elif entry.suffix == ".md":
                if matching is not None:
                    if child_rel not in matching:
                        continue
                else:
                    status = self._status_map.get(child_rel, _STATUS_NEW)
                    if not self._full_view and status in (_STATUS_SYNCED, _STATUS_EXCLUDED):
                        continue
                status = self._status_map.get(child_rel, _STATUS_NEW)
                node.add_leaf(
                    _file_label(entry.name, status),
                    data=NodeData(child_rel, False, entry),
                )
                has_visible = True

        return has_visible

    def _update_subtitle(self) -> None:
        root = self._dir_stats_cache.get("", DirStats())
        if self._search_text:
            mode_str = f"[bold cyan]Search: {self._search_mode}[/]"
        elif not self._full_view:
            mode_str = "[bold green]New only[/]"
        else:
            mode_str = "[bold yellow]Full[/]"
        self.sub_title = (
            f"Pool: {root.pending} pending  "
            f"| {root.new} new  "
            f"| {root.synced} synced  "
            f"| View: {mode_str}"
        )

    # ── Preview ──────────────────────────────────────────────────────────────

    def _update_preview(self, nd: NodeData | None) -> None:
        content = self._preview_content(nd)

        async def _do() -> None:
            preview = self.query_one("#preview-pane", Markdown)
            await preview.update(content)

        # Pass the callable _do (not the coroutine _do()) so Textual only creates
        # the coroutine when it actually runs the worker.  If exclusive=True cancels
        # a previous worker before it starts, no coroutine is ever created for it
        # and Python won't warn "coroutine was never awaited".
        self.run_worker(_do, exclusive=True, group="preview")

    def _preview_content(self, nd: NodeData | None) -> str:
        if nd is None:
            return ""

        if nd.is_dir:
            s = self._dir_stats_cache.get(nd.rel_path, DirStats())
            name = nd.abs_path.name or self.vault.name
            lines = [
                f"## 📁 {name}/",
                "",
                f"| Status   | Count |",
                f"|----------|-------|",
                f"| new      | {s.new} |",
                f"| pending  | {s.pending} |",
                f"| synced   | {s.synced} |",
                f"| excluded | {s.excluded} |",
                f"| **total**| **{s.total}** |",
            ]
            return "\n".join(lines)

        # File preview
        try:
            text = nd.abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"*Could not read file: {exc}*"

        status = self._status_map.get(nd.rel_path, _STATUS_NEW)
        status_badge = {
            _STATUS_NEW:      "🟢 new",
            _STATUS_PENDING:  "🟡 pending (in pool)",
            _STATUS_SYNCED:   "✅ synced",
            _STATUS_EXCLUDED: "🚫 excluded",
        }.get(status, status)

        header = f"**{nd.abs_path.name}** — {status_badge}\n\n---\n\n"

        if len(text) > _PREVIEW_MAX_CHARS:
            text = text[:_PREVIEW_MAX_CHARS] + "\n\n*…[truncated]*"

        return header + text

    # ── Events ───────────────────────────────────────────────────────────────

    @on(Tree.NodeHighlighted)
    def _on_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        self._current_node = event.node.data
        self._update_preview(event.node.data)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _collect_with_status(self, nd: NodeData, statuses: set[str]) -> list[str]:
        if not nd.is_dir:
            status = self._status_map.get(nd.rel_path, _STATUS_NEW)
            return [nd.rel_path] if status in statuses else []
        result: list[str] = []
        on_disk: set[str] = set()
        for f in nd.abs_path.rglob("*.md"):
            rel_parts = f.relative_to(self.vault).parts
            if any(part in self._exclude_dirs for part in rel_parts[:-1]):
                continue
            rel = f.relative_to(self.vault).as_posix()
            on_disk.add(rel)
            if self._status_map.get(rel, _STATUS_NEW) in statuses:
                result.append(rel)
        # Also collect orphaned entries (in status_map but not on disk).
        prefix = (nd.rel_path + "/") if nd.rel_path else ""
        for rel, status in self._status_map.items():
            if rel not in on_disk and status in statuses:
                if not nd.rel_path or rel.startswith(prefix):
                    result.append(rel)
        return result

    def _notify_empty(self, action: str) -> None:
        self.notify(f"Nothing to {action} here.", severity="warning", timeout=2)

    # ── Actions ──────────────────────────────────────────────────────────────

    def action_include(self) -> None:
        nd = self._current_node
        if nd is None:
            return
        targets = self._collect_with_status(nd, {_STATUS_NEW})
        if not targets:
            self._notify_empty("include")
            return
        now = datetime.utcnow().isoformat()
        for rel in targets:
            self.store.upsert_pool_item("obsidian", rel, _STATUS_PENDING, {}, added_at=now)
            self._status_map[rel] = _STATUS_PENDING
        self.notify(f"Added {len(targets)} file(s) to pool.", timeout=2)
        self._refresh_tree()

    def action_remove(self) -> None:
        nd = self._current_node
        if nd is None:
            return
        targets = self._collect_with_status(nd, {_STATUS_PENDING})
        if not targets:
            self._notify_empty("remove")
            return
        for rel in targets:
            self.store.remove_from_pool("obsidian", rel)
            self._status_map[rel] = _STATUS_NEW
        self.notify(f"Removed {len(targets)} file(s) from pool.", timeout=2)
        self._refresh_tree()

    def action_exclude(self) -> None:
        nd = self._current_node
        if nd is None:
            return
        targets = self._collect_with_status(nd, {_STATUS_NEW, _STATUS_PENDING})
        if not targets:
            self._notify_empty("exclude")
            return
        now = datetime.utcnow().isoformat()
        for rel in targets:
            self.store.upsert_pool_item("obsidian", rel, _STATUS_EXCLUDED, {}, added_at=now)
            self._status_map[rel] = _STATUS_EXCLUDED
        self.notify(f"Excluded {len(targets)} file(s).", timeout=2)
        self._refresh_tree()

    def action_clean(self) -> None:
        nd = self._current_node
        if nd is None:
            return
        targets = self._collect_with_status(nd, {_STATUS_SYNCED})
        if not targets:
            self._notify_empty("clean")
            return
        for rel in targets:
            self.store.delete_document("obsidian", rel)
            self.store.remove_from_pool("obsidian", rel)
            del self._status_map[rel]
        self.notify(f"Cleaned {len(targets)} file(s) from corpus.", timeout=2)
        self._refresh_tree()

    def action_toggle_view(self) -> None:
        self._full_view = not self._full_view
        self._refresh_tree()


# ── Normalisation ─────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Accent-insensitive, case-insensitive, separator-insensitive normalisation.

    Strips combining diacritics, lowercases, and removes -, _, and whitespace so
    that e.g. "Héllo-World", "hello world", "hello_world" all normalise to "helloworld".
    """
    nfkd = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[-_\s]+", "", no_accents.lower())


# ── Tree expand helpers ───────────────────────────────────────────────────────

def _collect_expanded(node) -> set[str]:
    """Return rel_paths of every currently-expanded directory node."""
    result: set[str] = set()
    for child in node.children:
        if child.is_expanded and child.data is not None and child.data.is_dir:
            result.add(child.data.rel_path)
        result |= _collect_expanded(child)
    return result


def _restore_expanded(node, expanded: set[str]) -> None:
    """Expand any node whose rel_path appears in *expanded*."""
    for child in node.children:
        if child.data is not None and child.data.is_dir and child.data.rel_path in expanded:
            child.expand()
        _restore_expanded(child, expanded)


# ── Label helpers ─────────────────────────────────────────────────────────────

def _inc(stats: dict[str, DirStats], rel: str, status: str) -> None:
    if rel not in stats:
        stats[rel] = DirStats()
    s = stats[rel]
    if status == _STATUS_NEW:
        s.new += 1
    elif status == _STATUS_PENDING:
        s.pending += 1
    elif status == _STATUS_SYNCED:
        s.synced += 1
    elif status == _STATUS_EXCLUDED:
        s.excluded += 1


def _dir_label(name: str, s: DirStats, full: bool) -> Text:
    t = Text()
    t.append("📁 ")
    t.append(name + "/", style="bold")
    badges: list[tuple[str, str]] = []
    if s.new:
        badges.append((f" {s.new} new", "green"))
    if s.pending:
        badges.append((f" {s.pending} pending", "yellow"))
    if full:
        if s.synced:
            badges.append((f" {s.synced} synced", "dim"))
        if s.excluded:
            badges.append((f" {s.excluded} excl.", "dim red"))
    if badges:
        t.append("  ")
        for i, (label, style) in enumerate(badges):
            if i:
                t.append(" ·", style="dim")
            t.append(label, style=style)
    return t


def _file_label(name: str, status: str) -> Text:
    t = Text()
    if status == _STATUS_NEW:
        t.append("📄 ")
        t.append(name, style="white")
        t.append("  [new]", style="green")
    elif status == _STATUS_PENDING:
        t.append("📄 ")
        t.append(name, style="yellow bold")
        t.append("  [→ pool]", style="yellow")
    elif status == _STATUS_SYNCED:
        t.append("📄 ", style="dim")
        t.append(name, style="dim")
        t.append("  [✓]", style="dim")
    elif status == _STATUS_EXCLUDED:
        t.append("📄 ", style="dim red")
        t.append(name, style="dim red strike")
        t.append("  [✗]", style="dim red")
    else:
        t.append("📄 ")
        t.append(name)
    return t


# ── Entry point ───────────────────────────────────────────────────────────────

def run_obsidian_scan_tui(
    vault: Path,
    store: SQLAlchemyStore,
    extra_exclude_dirs: set[str] | None = None,
) -> None:
    status_map: dict[str, str] = {}

    for source_id in store.get_indexed_id_dates("obsidian"):
        status_map[source_id] = _STATUS_SYNCED

    for source_id, status in store.get_pool_ids("obsidian").items():
        status_map[source_id] = status

    app = ObsidianScanApp(vault, status_map, store, extra_exclude_dirs)
    app.run()
