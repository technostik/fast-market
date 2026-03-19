from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

import sqlite3

from core.models import Action, Rule, Source, TriggerLog, ItemMetadata


class MonitorStorage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY,
                    plugin TEXT NOT NULL,
                    identifier TEXT NOT NULL,
                    description TEXT,
                    enabled INTEGER DEFAULT 1,
                    last_check TEXT,
                    last_fetched_at TEXT,
                    last_item_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    command TEXT NOT NULL,
                    description TEXT,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_run TEXT,
                    last_output TEXT,
                    last_exit_code INTEGER
                );

                CREATE TABLE IF NOT EXISTS rules (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    conditions TEXT NOT NULL,
                    action_ids TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    description TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trigger_logs (
                    id TEXT PRIMARY KEY,
                    rule_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    item_title TEXT NOT NULL,
                    item_url TEXT NOT NULL,
                    triggered_at TEXT NOT NULL,
                    exit_code INTEGER,
                    output TEXT,
                    FOREIGN KEY (rule_id) REFERENCES rules(id),
                    FOREIGN KEY (source_id) REFERENCES sources(id),
                    FOREIGN KEY (action_id) REFERENCES actions(id)
                );

                CREATE INDEX IF NOT EXISTS idx_trigger_logs_item
                ON trigger_logs(item_id, source_id);

                CREATE INDEX IF NOT EXISTS idx_trigger_logs_rule
                ON trigger_logs(rule_id, triggered_at);
            """)

            try:
                conn.execute("""
                    ALTER TABLE sources ADD COLUMN last_fetched_at TEXT
                """)
            except Exception:
                pass

    @contextmanager
    def _get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get_all_sources(self) -> list[Source]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM sources WHERE enabled = 1").fetchall()
            return [self._row_to_source(row) for row in rows]

    def get_source(self, source_id: str) -> Source | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
            return self._row_to_source(row) if row else None

    def add_source(self, source: Source) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO sources (id, plugin, identifier, description, enabled, last_check, last_fetched_at, last_item_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source.id,
                    source.plugin,
                    source.identifier,
                    source.description,
                    int(source.enabled),
                    source.last_check.isoformat() if source.last_check else None,
                    source.last_fetched_at.isoformat() if source.last_fetched_at else None,
                    source.last_item_id,
                    source.created_at.isoformat(),
                ),
            )

    def update_source(self, source: Source) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE sources SET plugin = ?, identifier = ?, description = ?, enabled = ?,
                   last_check = ?, last_fetched_at = ?, last_item_id = ? WHERE id = ?""",
                (
                    source.plugin,
                    source.identifier,
                    source.description,
                    int(source.enabled),
                    source.last_check.isoformat() if source.last_check else None,
                    source.last_fetched_at.isoformat() if source.last_fetched_at else None,
                    source.last_item_id,
                    source.id,
                ),
            )

    def update_source_last_check(self, source_id: str, last_item_id: str | None) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE sources SET last_check = ?, last_item_id = ? WHERE id = ?",
                (datetime.now().isoformat(), last_item_id, source_id),
            )

    def update_source_last_fetched_at(self, source_id: str, last_fetched_at: datetime) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE sources SET last_fetched_at = ? WHERE id = ?",
                (last_fetched_at.isoformat(), source_id),
            )

    def delete_source(self, source_id: str) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    def get_all_actions(self) -> list[Action]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM actions WHERE enabled = 1").fetchall()
            return [self._row_to_action(row) for row in rows]

    def get_action(self, action_id: str) -> Action | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
            return self._row_to_action(row) if row else None

    def add_action(self, action: Action) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO actions (id, name, command, description, enabled, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    action.id,
                    action.name,
                    action.command,
                    action.description,
                    int(action.enabled),
                    action.created_at.isoformat(),
                ),
            )

    def update_action(self, action: Action) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE actions SET name = ?, command = ?, description = ?, enabled = ?,
                   last_run = ?, last_output = ?, last_exit_code = ? WHERE id = ?""",
                (
                    action.name,
                    action.command,
                    action.description,
                    int(action.enabled),
                    action.last_run.isoformat() if action.last_run else None,
                    action.last_output,
                    action.last_exit_code,
                    action.id,
                ),
            )

    def delete_action(self, action_id: str) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM actions WHERE id = ?", (action_id,))

    def get_all_rules(self) -> list[Rule]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM rules WHERE enabled = 1").fetchall()
            return [self._row_to_rule(row) for row in rows]

    def get_rule(self, rule_id: str) -> Rule | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
            return self._row_to_rule(row) if row else None

    def add_rule(self, rule: Rule) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO rules (id, name, conditions, action_ids, enabled, description, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    rule.id,
                    rule.name,
                    json.dumps(rule.conditions),
                    json.dumps(rule.action_ids),
                    int(rule.enabled),
                    rule.description,
                    rule.created_at.isoformat(),
                ),
            )

    def update_rule(self, rule: Rule) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE rules SET name = ?, conditions = ?, action_ids = ?, enabled = ?,
                   description = ? WHERE id = ?""",
                (
                    rule.name,
                    json.dumps(rule.conditions),
                    json.dumps(rule.action_ids),
                    int(rule.enabled),
                    rule.description,
                    rule.id,
                ),
            )

    def delete_rule(self, rule_id: str) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))

    def log_trigger(self, log: TriggerLog) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO trigger_logs
                   (id, rule_id, source_id, action_id, item_id, item_title,
                    item_url, triggered_at, exit_code, output)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    log.id,
                    log.rule_id,
                    log.source_id,
                    log.action_id,
                    log.item_id,
                    log.item_title,
                    log.item_url,
                    log.triggered_at.isoformat(),
                    log.exit_code,
                    log.output,
                ),
            )

    def get_trigger_logs(
        self,
        since: datetime | None = None,
        rule_id: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[TriggerLog]:
        with self._get_conn() as conn:
            query = "SELECT * FROM trigger_logs WHERE 1=1"
            params: list = []

            if since:
                query += " AND triggered_at >= ?"
                params.append(since.isoformat())
            if rule_id:
                query += " AND rule_id = ?"
                params.append(rule_id)
            if source_id:
                query += " AND source_id = ?"
                params.append(source_id)

            query += " ORDER BY triggered_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [self._row_to_trigger_log(row) for row in rows]

    def get_stats(self) -> dict:
        with self._get_conn() as conn:
            sources = conn.execute("SELECT COUNT(*) FROM sources WHERE enabled = 1").fetchone()[0]
            actions = conn.execute("SELECT COUNT(*) FROM actions WHERE enabled = 1").fetchone()[0]
            rules = conn.execute("SELECT COUNT(*) FROM rules WHERE enabled = 1").fetchone()[0]
            triggers = conn.execute("SELECT COUNT(*) FROM trigger_logs").fetchone()[0]
            failed_triggers = conn.execute(
                "SELECT COUNT(*) FROM trigger_logs WHERE exit_code != 0"
            ).fetchone()[0]

            last_trigger = conn.execute(
                "SELECT triggered_at FROM trigger_logs ORDER BY triggered_at DESC LIMIT 1"
            ).fetchone()

            return {
                "sources_count": sources,
                "actions_count": actions,
                "rules_count": rules,
                "triggers_count": triggers,
                "failed_triggers_count": failed_triggers,
                "last_trigger_at": last_trigger[0] if last_trigger else None,
            }

    def _row_to_source(self, row: sqlite3.Row) -> Source:
        last_fetched_at_val = row["last_fetched_at"] if "last_fetched_at" in row.keys() else None
        return Source(
            id=row["id"],
            plugin=row["plugin"],
            identifier=row["identifier"],
            description=row["description"],
            enabled=bool(row["enabled"]),
            last_check=datetime.fromisoformat(row["last_check"]) if row["last_check"] else None,
            last_fetched_at=datetime.fromisoformat(last_fetched_at_val)
            if last_fetched_at_val
            else None,
            last_item_id=row["last_item_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _row_to_action(self, row: sqlite3.Row) -> Action:
        return Action(
            id=row["id"],
            name=row["name"],
            command=row["command"],
            description=row["description"],
            enabled=bool(row["enabled"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            last_run=datetime.fromisoformat(row["last_run"]) if row["last_run"] else None,
            last_output=row["last_output"],
            last_exit_code=row["last_exit_code"],
        )

    def _row_to_rule(self, row: sqlite3.Row) -> Rule:
        return Rule(
            id=row["id"],
            name=row["name"],
            conditions=json.loads(row["conditions"]),
            action_ids=json.loads(row["action_ids"]),
            enabled=bool(row["enabled"]),
            description=row["description"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _row_to_trigger_log(self, row: sqlite3.Row) -> TriggerLog:
        return TriggerLog(
            id=row["id"],
            rule_id=row["rule_id"],
            source_id=row["source_id"],
            action_id=row["action_id"],
            item_id=row["item_id"],
            item_title=row["item_title"],
            item_url=row["item_url"],
            triggered_at=datetime.fromisoformat(row["triggered_at"]),
            exit_code=row["exit_code"],
            output=row["output"],
        )
