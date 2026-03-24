from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

import sqlite3

from core.models import (
    Action,
    Rule,
    RuleMismatchLog,
    Source,
    TriggerLog,
    TriggerLogWithMetadata,
)


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
                    origin TEXT NOT NULL,
                    description TEXT,
                    metadata TEXT DEFAULT '{}',
                    enabled INTEGER DEFAULT 1,
                    last_check TEXT,
                    last_fetched_at TEXT,
                    last_item_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY,
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
                    conditions TEXT NOT NULL,
                    action_ids TEXT NOT NULL,
                    on_error_action_ids TEXT DEFAULT '[]',
                    on_execution_action_ids TEXT DEFAULT '[]',
                    enabled INTEGER DEFAULT 1,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    schedule TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    last_triggered_at TEXT
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
                    item_extra TEXT,
                    FOREIGN KEY (rule_id) REFERENCES rules(id),
                    FOREIGN KEY (source_id) REFERENCES sources(id),
                    FOREIGN KEY (action_id) REFERENCES actions(id)
                );

                CREATE TABLE IF NOT EXISTS rule_mismatch_logs (
                    id TEXT PRIMARY KEY,
                    rule_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    item_title TEXT NOT NULL,
                    failed_conditions TEXT NOT NULL,
                    evaluated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_trigger_logs_item
                ON trigger_logs(item_id, source_id);

                CREATE INDEX IF NOT EXISTS idx_trigger_logs_rule
                ON trigger_logs(rule_id, triggered_at);

                CREATE INDEX IF NOT EXISTS idx_mismatch_logs_rule
                ON rule_mismatch_logs(rule_id, evaluated_at);

                CREATE INDEX IF NOT EXISTS idx_mismatch_logs_source
                ON rule_mismatch_logs(source_id, evaluated_at);
            """)
            self._migrate_rules_columns(conn)
            self._migrate_sources_columns(conn)

    @contextmanager
    def _get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _migrate_rules_columns(self, conn: sqlite3.Connection) -> None:
        try:
            result = conn.execute("SELECT on_error_action_ids FROM rules LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            try:
                conn.execute("ALTER TABLE rules ADD COLUMN on_error_action_ids TEXT DEFAULT '[]'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute(
                    "ALTER TABLE rules ADD COLUMN on_execution_action_ids TEXT DEFAULT '[]'"
                )
            except sqlite3.OperationalError:
                pass

    def _migrate_sources_columns(self, conn: sqlite3.Connection) -> None:
        try:
            conn.execute("SELECT check_interval FROM sources LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            try:
                conn.execute("ALTER TABLE sources ADD COLUMN check_interval INTEGER")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE sources ADD COLUMN is_new INTEGER DEFAULT 1")
            except sqlite3.OperationalError:
                pass

    def get_all_sources(self, include_disabled: bool = False) -> list[Source]:
        with self._get_conn() as conn:
            if include_disabled:
                rows = conn.execute("SELECT * FROM sources").fetchall()
            else:
                rows = conn.execute("SELECT * FROM sources WHERE enabled = 1").fetchall()
            return [self._row_to_source(row) for row in rows]

    def get_source(self, source_id: str) -> Source | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
            return self._row_to_source(row) if row else None

    def add_source(self, source: Source) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO sources (id, plugin, origin, description, metadata, enabled, last_check, last_fetched_at, last_item_id, check_interval, is_new, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source.id,
                    source.plugin,
                    source.origin,
                    source.description,
                    json.dumps(source.metadata),
                    int(source.enabled),
                    source.last_check.isoformat() if source.last_check else None,
                    source.last_fetched_at.isoformat() if source.last_fetched_at else None,
                    source.last_item_id,
                    source.check_interval,
                    int(source.is_new),
                    source.created_at.isoformat(),
                ),
            )

    def update_source(self, source: Source) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE sources SET plugin = ?, origin = ?, description = ?, metadata = ?, enabled = ?,
                   last_check = ?, last_fetched_at = ?, last_item_id = ?, check_interval = ?, is_new = ? WHERE id = ?""",
                (
                    source.plugin,
                    source.origin,
                    source.description,
                    json.dumps(source.metadata),
                    int(source.enabled),
                    source.last_check.isoformat() if source.last_check else None,
                    source.last_fetched_at.isoformat() if source.last_fetched_at else None,
                    source.last_item_id,
                    source.check_interval,
                    int(source.is_new),
                    source.id,
                ),
            )

    def update_source_last_check(self, source_id: str, last_item_id: str | None) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE sources SET last_check = ?, last_item_id = ? WHERE id = ?",
                (datetime.now().isoformat(), last_item_id, source_id),
            )

    def update_source_last_check_time(self, source_id: str, last_check: datetime) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE sources SET last_check = ? WHERE id = ?",
                (last_check.isoformat(), source_id),
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

    def get_all_actions(self, include_disabled: bool = False) -> list[Action]:
        with self._get_conn() as conn:
            if include_disabled:
                rows = conn.execute("SELECT * FROM actions").fetchall()
            else:
                rows = conn.execute("SELECT * FROM actions WHERE enabled = 1").fetchall()
            return [self._row_to_action(row) for row in rows]

    def get_action(self, action_id: str) -> Action | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
            return self._row_to_action(row) if row else None

    def add_action(self, action: Action) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO actions (id, command, description, enabled, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    action.id,
                    action.command,
                    action.description,
                    int(action.enabled),
                    action.created_at.isoformat(),
                ),
            )

    def update_action(self, action: Action) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE actions SET command = ?, description = ?, enabled = ?,
                   last_run = ?, last_output = ?, last_exit_code = ? WHERE id = ?""",
                (
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

    def get_all_rules(self, include_disabled: bool = False) -> list[Rule]:
        with self._get_conn() as conn:
            if include_disabled:
                rows = conn.execute("SELECT * FROM rules").fetchall()
            else:
                rows = conn.execute("SELECT * FROM rules WHERE enabled = 1").fetchall()
            return [self._row_to_rule(row) for row in rows]

    def get_rule(self, rule_id: str) -> Rule | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
            return self._row_to_rule(row) if row else None

    def add_rule(self, rule: Rule) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO rules (id, conditions, action_ids, on_error_action_ids, on_execution_action_ids, enabled, description, created_at, schedule, timezone, last_triggered_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rule.id,
                    json.dumps(rule.conditions),
                    json.dumps(rule.action_ids),
                    json.dumps(rule.on_error_action_ids),
                    json.dumps(rule.on_execution_action_ids),
                    int(rule.enabled),
                    rule.description,
                    rule.created_at.isoformat(),
                    json.dumps(rule.schedule) if rule.schedule else None,
                    rule.timezone,
                    rule.last_triggered_at.isoformat() if rule.last_triggered_at else None,
                ),
            )

    def update_rule(self, rule: Rule) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE rules SET conditions = ?, action_ids = ?, on_error_action_ids = ?, on_execution_action_ids = ?, enabled = ?,
                   description = ?, schedule = ?, timezone = ?, last_triggered_at = ? WHERE id = ?""",
                (
                    json.dumps(rule.conditions),
                    json.dumps(rule.action_ids),
                    json.dumps(rule.on_error_action_ids),
                    json.dumps(rule.on_execution_action_ids),
                    int(rule.enabled),
                    rule.description,
                    json.dumps(rule.schedule) if rule.schedule else None,
                    rule.timezone,
                    rule.last_triggered_at.isoformat() if rule.last_triggered_at else None,
                    rule.id,
                ),
            )

    def delete_rule(self, rule_id: str) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))

    def update_rule_last_triggered_at(self, rule_id: str, last_triggered_at: datetime) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE rules SET last_triggered_at = ? WHERE id = ?",
                (last_triggered_at.isoformat(), rule_id),
            )

    def clean_trigger_logs(
        self, since: datetime | None = None, before: datetime | None = None
    ) -> int:
        with self._get_conn() as conn:
            query = "DELETE FROM trigger_logs WHERE 1=1"
            params: list = []
            if since:
                query += " AND triggered_at >= ?"
                params.append(since.isoformat())
            if before:
                query += " AND triggered_at <= ?"
                params.append(before.isoformat())
            cur = conn.execute(query, params)
            return cur.rowcount

    def log_trigger(self, log: TriggerLog) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO trigger_logs
                   (id, rule_id, source_id, action_id, item_id, item_title,
                    item_url, item_extra, triggered_at, exit_code, output)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    log.id,
                    log.rule_id,
                    log.source_id,
                    log.action_id,
                    log.item_id,
                    log.item_title,
                    log.item_url,
                    json.dumps(log.item_extra) if log.item_extra else None,
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
        action_id: str | None = None,
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
            if action_id:
                query += " AND action_id = ?"
                params.append(action_id)

            query += " ORDER BY triggered_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [self._row_to_trigger_log(row) for row in rows]

    def get_trigger_logs_with_metadata(
        self,
        since: datetime | None = None,
        rule_id: str | None = None,
        source_id: str | None = None,
        action_id: str | None = None,
        meta_key: str | None = None,
        meta_value: str | None = None,
        limit: int = 100,
    ) -> list[TriggerLogWithMetadata]:
        with self._get_conn() as conn:
            query = """
                SELECT t.*, s.metadata as source_metadata
                FROM trigger_logs t
                LEFT JOIN sources s ON t.source_id = s.id
                WHERE 1=1
            """
            params: list = []

            if since:
                query += " AND t.triggered_at >= ?"
                params.append(since.isoformat())
            if rule_id:
                query += " AND t.rule_id = ?"
                params.append(rule_id)
            if source_id:
                query += " AND t.source_id = ?"
                params.append(source_id)
            if action_id:
                query += " AND t.action_id = ?"
                params.append(action_id)

            if meta_key and meta_value:
                query += " AND s.metadata LIKE ?"
                params.append(f'%"' + meta_key + '":"' + meta_value + '"%')

            query += " ORDER BY t.triggered_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [self._row_to_trigger_log_with_metadata(row) for row in rows]

    def log_rule_mismatch(self, log: RuleMismatchLog) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO rule_mismatch_logs
                   (id, rule_id, source_id, item_id, item_title, failed_conditions, evaluated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    log.id,
                    log.rule_id,
                    log.source_id,
                    log.item_id,
                    log.item_title,
                    json.dumps(log.failed_conditions),
                    log.evaluated_at.isoformat(),
                ),
            )

    def get_rule_mismatch_logs(
        self,
        since: datetime | None = None,
        rule_id: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[RuleMismatchLog]:
        with self._get_conn() as conn:
            query = "SELECT * FROM rule_mismatch_logs WHERE 1=1"
            params: list = []

            if since:
                query += " AND evaluated_at >= ?"
                params.append(since.isoformat())
            if rule_id:
                query += " AND rule_id = ?"
                params.append(rule_id)
            if source_id:
                query += " AND source_id = ?"
                params.append(source_id)

            query += " ORDER BY evaluated_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [self._row_to_mismatch_log(row) for row in rows]

    def clean_rule_mismatch_logs(
        self, since: datetime | None = None, before: datetime | None = None
    ) -> int:
        with self._get_conn() as conn:
            query = "DELETE FROM rule_mismatch_logs WHERE 1=1"
            params: list = []
            if since:
                query += " AND evaluated_at >= ?"
                params.append(since.isoformat())
            if before:
                query += " AND evaluated_at <= ?"
                params.append(before.isoformat())
            cur = conn.execute(query, params)
            return cur.rowcount

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
        metadata_val = row["metadata"] if "metadata" in row.keys() else "{}"
        check_interval_val = row["check_interval"] if "check_interval" in row.keys() else None
        is_new_val = row["is_new"] if "is_new" in row.keys() else 0
        return Source(
            id=row["id"],
            plugin=row["plugin"],
            origin=row["origin"],
            description=row["description"],
            metadata=json.loads(metadata_val) if metadata_val else {},
            enabled=bool(row["enabled"]),
            last_check=datetime.fromisoformat(row["last_check"]) if row["last_check"] else None,
            last_fetched_at=datetime.fromisoformat(last_fetched_at_val)
            if last_fetched_at_val
            else None,
            last_item_id=row["last_item_id"],
            check_interval=check_interval_val,
            is_new=bool(is_new_val),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _row_to_action(self, row: sqlite3.Row) -> Action:
        return Action(
            id=row["id"],
            command=row["command"],
            description=row["description"],
            enabled=bool(row["enabled"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            last_run=datetime.fromisoformat(row["last_run"]) if row["last_run"] else None,
            last_output=row["last_output"],
            last_exit_code=row["last_exit_code"],
        )

    def _row_to_rule(self, row: sqlite3.Row) -> Rule:
        schedule_val = row["schedule"] if "schedule" in row.keys() else None
        timezone_val = row["timezone"] if "timezone" in row.keys() else "UTC"
        last_triggered_val = row["last_triggered_at"] if "last_triggered_at" in row.keys() else None
        on_error_val = row["on_error_action_ids"] if "on_error_action_ids" in row.keys() else "[]"
        on_execution_val = (
            row["on_execution_action_ids"] if "on_execution_action_ids" in row.keys() else "[]"
        )

        return Rule(
            id=row["id"],
            conditions=json.loads(row["conditions"]),
            action_ids=json.loads(row["action_ids"]),
            on_error_action_ids=json.loads(on_error_val) if on_error_val else [],
            on_execution_action_ids=json.loads(on_execution_val) if on_execution_val else [],
            enabled=bool(row["enabled"]),
            description=row["description"],
            created_at=datetime.fromisoformat(row["created_at"]),
            schedule=json.loads(schedule_val) if schedule_val else None,
            timezone=timezone_val,
            last_triggered_at=datetime.fromisoformat(last_triggered_val)
            if last_triggered_val
            else None,
        )

    def _row_to_trigger_log(self, row: sqlite3.Row) -> TriggerLog:
        extra_val = row["item_extra"] if "item_extra" in row.keys() else None
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
            item_extra=json.loads(extra_val) if extra_val else None,
        )

    def _row_to_trigger_log_with_metadata(self, row: sqlite3.Row) -> TriggerLogWithMetadata:
        base = self._row_to_trigger_log(row)
        metadata_val = row["source_metadata"] if "source_metadata" in row.keys() else "{}"
        metadata = json.loads(metadata_val) if metadata_val else None
        return TriggerLogWithMetadata(
            id=base.id,
            rule_id=base.rule_id,
            source_id=base.source_id,
            action_id=base.action_id,
            item_id=base.item_id,
            item_title=base.item_title,
            item_url=base.item_url,
            triggered_at=base.triggered_at,
            exit_code=base.exit_code,
            output=base.output,
            item_extra=base.item_extra,
            source_metadata=metadata,
        )

    def _row_to_mismatch_log(self, row: sqlite3.Row) -> RuleMismatchLog:
        return RuleMismatchLog(
            id=row["id"],
            rule_id=row["rule_id"],
            source_id=row["source_id"],
            item_id=row["item_id"],
            item_title=row["item_title"],
            failed_conditions=json.loads(row["failed_conditions"]),
            evaluated_at=datetime.fromisoformat(row["evaluated_at"]),
        )
