from __future__ import annotations

import click
from click.shell_completion import CompletionItem

from commands.helpers import get_storage


class RuleIdType(click.ParamType):
    name = "RULE_ID"

    def shell_complete(self, ctx, param, incomplete):
        try:
            storage = get_storage()
            rules = storage.get_all_rules(include_disabled=True)
        except Exception:
            return []

        return [
            CompletionItem(rule.id, help=rule.description or "")
            for rule in rules
            if rule.id.startswith(incomplete)
        ]

    def convert(self, value, param, ctx):
        return value


class SourceIdType(click.ParamType):
    name = "SOURCE_ID"

    def shell_complete(self, ctx, param, incomplete):
        try:
            storage = get_storage()
            sources = storage.get_all_sources(include_disabled=True)
        except Exception:
            return []

        return [
            CompletionItem(source.id, help=source.description or source.origin)
            for source in sources
            if source.id.startswith(incomplete)
        ]

    def convert(self, value, param, ctx):
        return value


class ActionIdType(click.ParamType):
    name = "ACTION_ID"

    def shell_complete(self, ctx, param, incomplete):
        try:
            storage = get_storage()
            actions = storage.get_all_actions(include_disabled=True)
        except Exception:
            return []

        return [
            CompletionItem(action.id, help=action.description or "")
            for action in actions
            if action.id.startswith(incomplete)
        ]

    def convert(self, value, param, ctx):
        return value
