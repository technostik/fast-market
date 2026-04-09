from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter


@dataclass
class PluginManifest:
    name: str
    tab_label: str
    tab_icon: str
    api_router: APIRouter
    frontend_html: str
