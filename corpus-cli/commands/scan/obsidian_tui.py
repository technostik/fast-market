"""Interactive Textual TUI for selecting Obsidian notes to add to the sync pool."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Tree
from textual import on

if TYPE_CHECKING:
    from storage.sqlalchemy_store import SQLAlchemyStore

_SYSTEM_DIRS = {".obsidian", ".trash", ".git"}

# Statuses managed in the pool / document store
_STATUS_NEW = "new"
_STATUS_PENDING = "pending"
_STATUS_SYNCED = "synced"
_STATUS_EXCLUDED = "excluded"


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
    Tree {
        height: 1fr;
        scrollbar-gutter: stable;
    }
    """

    BINDINGS = [
        Binding("i", "include", "Include", show=True),
        Binding("r", "remove", "Remove", show=True),
        Binding("x", "exclude", "Exclude", show=True),
        Binding("f", "toggle_view", "Full/New", show=True),
        Binding("q", "quit", "Quit", show=True),
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
        # live state: {rel_posix_path: status}
        self._status_map = status_map
        self.store = store
        self._exclude_dirs: set[str] = _SYSTEM_DIRS | (extra_exclude_dirs or set())
        self._full_view = False
        self._current_node: NodeData | None = None
        # computed once per refresh
        self._dir_stats_cache: dict[str, DirStats] = {}

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        yield Tree(
            Text.from_markup(f"[bold]📁 {self.vault.name}/[/]"),
            data=NodeData("", True, self.vault),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Corpus Scan — Obsidian"
        self._refresh_tree()

    # ── Tree construction ────────────────────────────────────────────────────

    def _refresh_tree(self) -> None:
        self._dir_stats_cache = self._compute_all_stats()
        tree = self.query_one(Tree)
        for child in list(tree.root.children):
            child.remove()
        self._populate_dir(tree.root, self.vault, "")
        tree.root.expand()
        self._update_subtitle()

    def _compute_all_stats(self) -> dict[str, DirStats]:
        """Single filesystem walk to compute DirStats for every directory."""
        stats: dict[str, DirStats] = {"": DirStats()}
        for f in self.vault.rglob("*.md"):
            rel_parts = f.relative_to(self.vault).parts
            # Skip files inside system-excluded dirs
            if any(part in self._exclude_dirs for part in rel_parts[:-1]):
                continue
            source_id = f.relative_to(self.vault).as_posix()
            status = self._status_map.get(source_id, _STATUS_NEW)
            # Accumulate into every ancestor directory (including vault root "")
            current_rel = ""
            _inc(stats, current_rel, status)
            for part in rel_parts[:-1]:
                current_rel = (current_rel + "/" + part).lstrip("/")
                _inc(stats, current_rel, status)
        return stats

    def _populate_dir(self, node, directory: Path, dir_rel: str) -> bool:
        """Add visible children of `directory` to `node`. Returns True if any added."""
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
                if not self._full_view and s.actionable == 0:
                    continue
                label = _dir_label(entry.name, s, self._full_view)
                child = node.add(label, data=NodeData(child_rel, True, entry))
                populated = self._populate_dir(child, entry, child_rel)
                if not populated:
                    child.remove()
                else:
                    has_visible = True

            elif entry.suffix == ".md":
                status = self._status_map.get(child_rel, _STATUS_NEW)
                if not self._full_view and status in (_STATUS_SYNCED, _STATUS_EXCLUDED):
                    continue
                node.add_leaf(_file_label(entry.name, status), data=NodeData(child_rel, False, entry))
                has_visible = True

        return has_visible

    def _update_subtitle(self) -> None:
        root_stats = self._dir_stats_cache.get("", DirStats())
        mode = "[bold green]New only[/]" if not self._full_view else "[bold yellow]Full[/]"
        self.sub_title = (
            f"Pool: {root_stats.pending} pending  "
            f"| {root_stats.new} new  "
            f"| {root_stats.synced} synced  "
            f"| View: {mode}"
        )

    # ── Events ───────────────────────────────────────────────────────────────

    @on(Tree.NodeHighlighted)
    def _on_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        self._current_node = event.node.data

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _collect_with_status(self, nd: NodeData, statuses: set[str]) -> list[str]:
        """Gather vault-relative paths under nd that currently have one of the given statuses."""
        if not nd.is_dir:
            status = self._status_map.get(nd.rel_path, _STATUS_NEW)
            return [nd.rel_path] if status in statuses else []
        result: list[str] = []
        for f in nd.abs_path.rglob("*.md"):
            rel_parts = f.relative_to(self.vault).parts
            if any(part in self._exclude_dirs for part in rel_parts[:-1]):
                continue
            rel = f.relative_to(self.vault).as_posix()
            if self._status_map.get(rel, _STATUS_NEW) in statuses:
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

    def action_toggle_view(self) -> None:
        self._full_view = not self._full_view
        self._refresh_tree()


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
    """Build the initial status map from store state and launch the TUI."""
    status_map: dict[str, str] = {}

    # Files already indexed in the document store → synced
    for source_id in store.get_indexed_id_dates("obsidian"):
        status_map[source_id] = _STATUS_SYNCED

    # Pool items override with their current status (pending / excluded / failed)
    for source_id, status in store.get_pool_ids("obsidian").items():
        # Pool 'synced' entries without a document entry stay synced
        status_map[source_id] = status

    app = ObsidianScanApp(vault, status_map, store, extra_exclude_dirs)
    app.run()
