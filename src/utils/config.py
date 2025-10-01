"""Configuration management using Pydantic Settings"""

import os
from typing import Optional
from pathlib import Path
import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerConfig(BaseSettings):
    """Server configuration"""
    host: str = "0.0.0.0"
    port: int = 10000
    public_url: str = Field(default="http://localhost:10000")


class EufyConfig(BaseSettings):
    """Eufy WebSocket configuration"""
    websocket_url: str = Field(default="ws://127.0.0.1:3000/ws")
    reconnect_delay: float = 5.0
    heartbeat_interval: float = 30.0


class RecordingConfig(BaseSettings):
    """Video recording configuration"""
    max_duration_seconds: int = 900
    motion_timeout_seconds: int = 60
    snooze_duration_seconds: int = 3600
    storage_path: str = "/mnt/recordings"
    retention_days: int = 90
    video_codec: str = "libx264"
    video_quality: str = "medium"


class WorkatoConfig(BaseSettings):
    """Workato webhook configuration"""
    webhook_url: str = Field(default="")
    timeout_seconds: int = 30
    rate_limit_per_second: int = 20


class RetryConfig(BaseSettings):
    """Retry configuration"""
    max_attempts: int = 3
    initial_delay: float = 1.0
    backoff_multiplier: float = 2.0


class ErrorLoggingConfig(BaseSettings):
    """Error logging configuration"""
    send_to_workato: bool = True
    keep_in_memory: int = 100


class StorageConfig(BaseSettings):
    """Storage management configuration"""
    cleanup_schedule: str = "0 3 * * *"
    min_free_space_gb: int = 5


class BatteryAlertConfig(BaseSettings):
    """Battery alert configuration"""
    cooldown_hours: int = 24


class MotionConfig(BaseSettings):
    """Motion detection configuration"""
    state_timeout_minutes: int = 60


class OfflineAlertConfig(BaseSettings):
    """Offline alert configuration"""
    polling_interval_minutes: int = 5
    failure_threshold: int = 3
    battery_threshold_percent: int = 30


class AlertsConfig(BaseSettings):
    """Alerts configuration"""
    battery: BatteryAlertConfig = Field(default_factory=BatteryAlertConfig)
    offline: OfflineAlertConfig = Field(default_factory=OfflineAlertConfig)


class LoggingConfig(BaseSettings):
    """Logging configuration"""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file: str = "./logs/eufy-security.log"
    max_size_mb: int = 100
    backup_count: int = 5


class AppConfig(BaseSettings):
    """Main application configuration"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    server: ServerConfig = Field(default_factory=ServerConfig)
    eufy: EufyConfig = Field(default_factory=EufyConfig)
    recording: RecordingConfig = Field(default_factory=RecordingConfig)
    workato: WorkatoConfig = Field(default_factory=WorkatoConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    error_logging: ErrorLoggingConfig = Field(default_factory=ErrorLoggingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    motion: MotionConfig = Field(default_factory=MotionConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    Load configuration from YAML file and environment variables

    Environment variables take precedence over YAML config

    Args:
        config_path: Path to YAML config file (default: config/config.yaml)

    Returns:
        AppConfig instance
    """
    if config_path is None:
        config_path = os.getenv("CONFIG_PATH", "config/config.yaml")

    config_file = Path(config_path)

    if not config_file.exists():
        # Return default config if file doesn't exist
        return AppConfig()

    with open(config_file, "r") as f:
        yaml_config = yaml.safe_load(f)

    # Expand environment variables in YAML
    yaml_config = _expand_env_vars(yaml_config)

    # Create nested config objects
    alerts_data = yaml_config.get("alerts", {})
    alerts_config = AlertsConfig(
        battery=BatteryAlertConfig(**alerts_data.get("battery", {})),
        offline=OfflineAlertConfig(**alerts_data.get("offline", {}))
    )

    config_dict = {
        "server": ServerConfig(**yaml_config.get("server", {})),
        "eufy": EufyConfig(**yaml_config.get("eufy", {})),
        "recording": RecordingConfig(**yaml_config.get("recording", {})),
        "workato": WorkatoConfig(**yaml_config.get("workato", {})),
        "retry": RetryConfig(**yaml_config.get("retry", {})),
        "error_logging": ErrorLoggingConfig(**yaml_config.get("error_logging", {})),
        "storage": StorageConfig(**yaml_config.get("storage", {})),
        "motion": MotionConfig(**yaml_config.get("motion", {})),
        "alerts": alerts_config,
        "logging": LoggingConfig(**yaml_config.get("logging", {})),
    }

    return AppConfig(**config_dict)


def _expand_env_vars(config: dict) -> dict:
    """Recursively expand environment variables in config dict"""
    if isinstance(config, dict):
        return {k: _expand_env_vars(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [_expand_env_vars(item) for item in config]
    elif isinstance(config, str):
        # Expand ${VAR_NAME:default_value} or ${VAR_NAME}
        if config.startswith("${") and config.endswith("}"):
            var_expr = config[2:-1]
            if ":" in var_expr:
                var_name, default = var_expr.split(":", 1)
                return os.getenv(var_name, default)
            else:
                return os.getenv(var_expr, config)
    return config