"""
Configuration Manager

Responsible for reading the JSON configuration file, validating all values,
parsing them into typed dataclasses, and persisting runtime changes (IP/Port).
"""

from __future__ import annotations

import ipaddress
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List


# ---------------------------------------------------------------------------
# Config data structures
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CounterConfig:
    id: int
    name: str


@dataclass(slots=True)
class GroupConfig:
    id: int
    name: str
    counters: List[CounterConfig]


@dataclass(slots=True)
class NetworkConfig:
    ip: str                     # device address to connect to
    port: int
    socket_timeout: float
    receive_buffer_size: int
    message_idle_ms: float      # quiet gap that marks a message as complete


@dataclass(slots=True)
class FontConfig:
    group_title: int
    counter_title: int
    token: int
    company_name: int


@dataclass(slots=True)
class BrandingConfig:
    logo_path: str
    company_name: str


@dataclass(slots=True)
class DisplayConfig:
    fullscreen: bool
    theme: str
    fonts: FontConfig
    branding: BrandingConfig
    groups: List[GroupConfig]


@dataclass(slots=True)
class RotationPolicy:
    max_bytes: int
    backup_count: int


@dataclass(slots=True)
class LoggingConfig:
    log_level: str
    log_file: str
    rotation_policy: RotationPolicy


@dataclass(slots=True)
class ApplicationConfig:
    debug_mode: bool
    startup_behaviour: str


@dataclass(slots=True)
class AppConfig:
    network: NetworkConfig
    display: DisplayConfig
    logging: LoggingConfig
    application: ApplicationConfig


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config(path: str | Path) -> AppConfig:
    """Load, validate, and return application configuration from a JSON file."""
    raw = _read_json(path)
    _validate(raw)
    return _parse(raw)


def save_network_settings(path: str | Path, ip: str, port: int) -> None:
    """
    Persist updated IP and Port to the JSON file.
    All other settings are left unchanged.
    """
    _validate_ip(ip)
    _validate_port(port)

    raw = _read_json(path)
    raw["network"]["ip"] = ip
    raw["network"]["port"] = port

    path = Path(path)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
# Internal — file reading
# ---------------------------------------------------------------------------

def _read_json(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Configuration file is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Configuration file must contain a JSON object at the top level.")
    return data


# ---------------------------------------------------------------------------
# Internal — validation
# ---------------------------------------------------------------------------

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _validate(raw: dict) -> None:
    _require_keys(raw, ["network", "display", "logging", "application"], context="root")
    _validate_network(raw["network"])
    _validate_display(raw["display"])
    _validate_logging(raw["logging"])
    _validate_application(raw["application"])


def _validate_network(net: dict) -> None:
    _require_keys(
        net,
        ["ip", "port", "socket_timeout", "receive_buffer_size", "message_idle_ms"],
        context="network",
    )
    _validate_ip(net["ip"])
    _validate_port(net["port"])
    if not isinstance(net["socket_timeout"], (int, float)) or net["socket_timeout"] <= 0:
        raise ValueError(
            f"network.socket_timeout must be a positive number, got: {net['socket_timeout']!r}"
        )
    if not isinstance(net["receive_buffer_size"], int) or net["receive_buffer_size"] <= 0:
        raise ValueError(
            f"network.receive_buffer_size must be a positive integer, "
            f"got: {net['receive_buffer_size']!r}"
        )
    if not isinstance(net["message_idle_ms"], (int, float)) or net["message_idle_ms"] <= 0:
        raise ValueError(
            f"network.message_idle_ms must be a positive number, "
            f"got: {net['message_idle_ms']!r}"
        )


def _validate_display(display: dict) -> None:
    _require_keys(
        display, ["fullscreen", "theme", "fonts", "branding", "groups"], context="display"
    )
    _validate_fonts(display["fonts"])
    _validate_branding(display["branding"])
    _validate_groups(display["groups"])


def _validate_fonts(fonts: dict) -> None:
    _require_keys(
        fonts, ["group_title", "counter_title", "token", "company_name"], context="display.fonts"
    )
    for key in ["group_title", "counter_title", "token", "company_name"]:
        if not isinstance(fonts[key], int) or fonts[key] <= 0:
            raise ValueError(
                f"display.fonts.{key} must be a positive integer, got: {fonts[key]!r}"
            )


def _validate_branding(branding: dict) -> None:
    _require_keys(branding, ["logo_path", "company_name"], context="display.branding")
    if not isinstance(branding["logo_path"], str):
        raise ValueError(
            f"display.branding.logo_path must be a string ('' omits the logo), "
            f"got: {branding['logo_path']!r}"
        )
    if not isinstance(branding["company_name"], str):
        raise ValueError(
            f"display.branding.company_name must be a string ('' omits the company name), "
            f"got: {branding['company_name']!r}"
        )


def _validate_groups(groups: list) -> None:
    if not isinstance(groups, list) or len(groups) == 0:
        raise ValueError("display.groups must be a non-empty list.")

    group_ids = []
    for i, group in enumerate(groups):
        ctx = f"display.groups[{i}]"
        _require_keys(group, ["id", "name", "counters"], context=ctx)
        if not isinstance(group["id"], int):
            raise ValueError(f"{ctx}.id must be an integer, got: {group['id']!r}")
        if not (0 <= group["id"] <= 9):
            raise ValueError(
                f"{ctx}.id must be a single digit (0-9) to fit the protocol's group field, "
                f"got: {group['id']!r}"
            )
        if not isinstance(group["name"], str) or not group["name"].strip():
            raise ValueError(f"{ctx}.name must be a non-empty string.")
        group_ids.append(group["id"])
        _validate_counters(group["counters"], ctx)

    if len(group_ids) != len(set(group_ids)):
        raise ValueError(f"Group IDs must be unique, got duplicates: {group_ids}")


def _validate_counters(counters: list, group_ctx: str) -> None:
    if not isinstance(counters, list) or len(counters) == 0:
        raise ValueError(f"{group_ctx}.counters must be a non-empty list.")

    counter_ids = []
    for i, counter in enumerate(counters):
        ctx = f"{group_ctx}.counters[{i}]"
        _require_keys(counter, ["id", "name"], context=ctx)
        if not isinstance(counter["id"], int):
            raise ValueError(f"{ctx}.id must be an integer, got: {counter['id']!r}")
        if not (0 <= counter["id"] <= 99):
            raise ValueError(
                f"{ctx}.id must be 0-99 (2 digits) to fit the protocol's counter field, "
                f"got: {counter['id']!r}"
            )
        if not isinstance(counter["name"], str) or not counter["name"].strip():
            raise ValueError(f"{ctx}.name must be a non-empty string.")
        counter_ids.append(counter["id"])

    if len(counter_ids) != len(set(counter_ids)):
        raise ValueError(
            f"{group_ctx} counter IDs must be unique, got duplicates: {counter_ids}"
        )


def _validate_logging(log: dict) -> None:
    _require_keys(log, ["log_level", "log_file", "rotation_policy"], context="logging")
    if log["log_level"] not in _VALID_LOG_LEVELS:
        raise ValueError(
            f"logging.log_level must be one of {_VALID_LOG_LEVELS}, got: {log['log_level']!r}"
        )
    if not isinstance(log["log_file"], str) or not log["log_file"].strip():
        raise ValueError("logging.log_file must be a non-empty string.")
    _validate_rotation_policy(log["rotation_policy"])


def _validate_rotation_policy(policy: dict) -> None:
    _require_keys(policy, ["max_bytes", "backup_count"], context="logging.rotation_policy")
    if not isinstance(policy["max_bytes"], int) or policy["max_bytes"] <= 0:
        raise ValueError(
            f"logging.rotation_policy.max_bytes must be a positive integer, "
            f"got: {policy['max_bytes']!r}"
        )
    if not isinstance(policy["backup_count"], int) or policy["backup_count"] <= 0:
        raise ValueError(
            f"logging.rotation_policy.backup_count must be a positive integer, "
            f"got: {policy['backup_count']!r}"
        )


def _validate_application(app: dict) -> None:
    _require_keys(app, ["debug_mode", "startup_behaviour"], context="application")
    if not isinstance(app["debug_mode"], bool):
        raise ValueError(
            f"application.debug_mode must be a boolean, got: {app['debug_mode']!r}"
        )
    if not isinstance(app["startup_behaviour"], str) or not app["startup_behaviour"].strip():
        raise ValueError("application.startup_behaviour must be a non-empty string.")


def _validate_ip(ip: str) -> None:
    if not isinstance(ip, str):
        raise ValueError(f"network.ip must be a string, got: {type(ip).__name__}")
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise ValueError(f"Invalid IP address: {ip!r}")


def _validate_port(port: int) -> None:
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ValueError(f"Port must be an integer between 1 and 65535, got: {port!r}")


def _require_keys(d: dict, keys: list, context: str) -> None:
    if not isinstance(d, dict):
        raise ValueError(f"{context} must be a mapping, got: {type(d).__name__}")
    missing = [k for k in keys if k not in d]
    if missing:
        raise ValueError(f"Missing required keys in {context}: {missing}")


# ---------------------------------------------------------------------------
# Internal — parsing
# ---------------------------------------------------------------------------

def _parse(raw: dict) -> AppConfig:
    return AppConfig(
        network=_parse_network(raw["network"]),
        display=_parse_display(raw["display"]),
        logging=_parse_logging(raw["logging"]),
        application=_parse_application(raw["application"]),
    )


def _parse_network(net: dict) -> NetworkConfig:
    return NetworkConfig(
        ip=net["ip"],
        port=int(net["port"]),
        socket_timeout=float(net["socket_timeout"]),
        receive_buffer_size=int(net["receive_buffer_size"]),
        message_idle_ms=float(net["message_idle_ms"]),
    )


def _parse_display(display: dict) -> DisplayConfig:
    return DisplayConfig(
        fullscreen=bool(display["fullscreen"]),
        theme=display["theme"],
        fonts=FontConfig(
            group_title=int(display["fonts"]["group_title"]),
            counter_title=int(display["fonts"]["counter_title"]),
            token=int(display["fonts"]["token"]),
            company_name=int(display["fonts"]["company_name"]),
        ),
        branding=_parse_branding(display["branding"]),
        groups=[_parse_group(g) for g in display["groups"]],
    )


def _parse_branding(branding: dict) -> BrandingConfig:
    return BrandingConfig(
        logo_path=branding["logo_path"],
        company_name=branding["company_name"],
    )


def _parse_group(group: dict) -> GroupConfig:
    return GroupConfig(
        id=int(group["id"]),
        name=group["name"],
        counters=[CounterConfig(id=int(c["id"]), name=c["name"]) for c in group["counters"]],
    )


def _parse_logging(log: dict) -> LoggingConfig:
    return LoggingConfig(
        log_level=log["log_level"],
        log_file=log["log_file"],
        rotation_policy=RotationPolicy(
            max_bytes=int(log["rotation_policy"]["max_bytes"]),
            backup_count=int(log["rotation_policy"]["backup_count"]),
        ),
    )


def _parse_application(app: dict) -> ApplicationConfig:
    return ApplicationConfig(
        debug_mode=bool(app["debug_mode"]),
        startup_behaviour=app["startup_behaviour"],
    )
