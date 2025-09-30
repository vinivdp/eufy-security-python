"""Tests for configuration management"""

import os
import tempfile
from pathlib import Path
import pytest
import yaml

from src.utils.config import (
    load_config,
    AppConfig,
    ServerConfig,
    AlertsConfig,
    BatteryAlertConfig,
    OfflineAlertConfig,
)


def test_default_config():
    """Test loading default configuration"""
    config = AppConfig()

    assert config.server.host == "0.0.0.0"
    assert config.server.port == 10000
    assert config.eufy.websocket_url == "ws://127.0.0.1:3000/ws"
    assert config.recording.max_duration_seconds == 900
    assert config.alerts.battery.cooldown_hours == 24
    assert config.alerts.offline.debounce_seconds == 30


def test_load_config_from_yaml(tmp_path: Path):
    """Test loading configuration from YAML file"""
    config_file = tmp_path / "config.yaml"
    config_data = {
        "server": {
            "host": "127.0.0.1",
            "port": 8080,
            "public_url": "http://custom.example.com"
        },
        "eufy": {
            "websocket_url": "ws://custom:3000/ws",
            "reconnect_delay": 10.0
        },
        "recording": {
            "max_duration_seconds": 600,
            "storage_path": "/custom/path"
        },
        "alerts": {
            "battery": {
                "cooldown_hours": 48
            },
            "offline": {
                "debounce_seconds": 60
            }
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    config = load_config(str(config_file))

    assert config.server.host == "127.0.0.1"
    assert config.server.port == 8080
    assert config.server.public_url == "http://custom.example.com"
    assert config.eufy.websocket_url == "ws://custom:3000/ws"
    assert config.eufy.reconnect_delay == 10.0
    assert config.recording.max_duration_seconds == 600
    assert config.recording.storage_path == "/custom/path"
    assert config.alerts.battery.cooldown_hours == 48
    assert config.alerts.offline.debounce_seconds == 60


def test_load_config_with_env_vars(tmp_path: Path):
    """Test loading configuration with environment variable expansion"""
    config_file = tmp_path / "config.yaml"
    config_data = {
        "server": {
            "public_url": "${PUBLIC_URL:http://default.example.com}"
        },
        "workato": {
            "webhook_url": "${WORKATO_URL}"
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    # Set environment variables
    os.environ["PUBLIC_URL"] = "http://env.example.com"
    os.environ["WORKATO_URL"] = "https://workato.example.com"

    try:
        config = load_config(str(config_file))

        assert config.server.public_url == "http://env.example.com"
        assert config.workato.webhook_url == "https://workato.example.com"
    finally:
        # Clean up
        del os.environ["PUBLIC_URL"]
        del os.environ["WORKATO_URL"]


def test_load_config_nonexistent_file():
    """Test loading config when file doesn't exist returns defaults"""
    config = load_config("/nonexistent/config.yaml")

    # Should return default config
    assert config.server.port == 10000
    assert config.recording.max_duration_seconds == 900


def test_nested_alerts_config():
    """Test nested alerts configuration structure"""
    alerts = AlertsConfig(
        battery=BatteryAlertConfig(cooldown_hours=12),
        offline=OfflineAlertConfig(debounce_seconds=15)
    )

    assert alerts.battery.cooldown_hours == 12
    assert alerts.offline.debounce_seconds == 15
