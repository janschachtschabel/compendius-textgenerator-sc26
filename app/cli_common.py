"""Shared wiring for CLI commands: registry from arguments or settings, service on top."""

from __future__ import annotations

import sys
from pathlib import Path

from app.main import build_service
from app.service import CompendiumService
from app.settings import get_settings
from app.sources.zim.registry import ZimRegistry
from app.templates.manager import TemplateManager


def cli_registry(zim_args: list[str] | None) -> ZimRegistry:
    """``--zim`` paths win, then ``ZIM_PATHS``, then ``active.json`` in ``ZIM_DIR``."""
    settings = get_settings()
    if zim_args:
        return ZimRegistry([Path(p) for p in zim_args])
    if settings.zim_path_list:
        return ZimRegistry(settings.zim_path_list)
    return ZimRegistry.from_active(settings.zim_dir)


def cli_service(zim_args: list[str] | None) -> CompendiumService:
    """Service for one CLI invocation; exits with code 2 when no archive is available."""
    settings = get_settings()
    registry = cli_registry(zim_args)
    if not registry.ready:
        print("Keine ZIM-Archive gefunden. --zim <pfad> angeben oder ZIM_DIR/ZIM_PATHS setzen.", file=sys.stderr)
        raise SystemExit(2)
    templates = TemplateManager(custom_dir=Path(settings.state_dir) / "templates")
    return build_service(settings, registry, templates)
