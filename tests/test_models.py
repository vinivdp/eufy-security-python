"""Tests for event models"""

from datetime import datetime
import pytest

from src.models.events import (
    MotionDetectedEvent,
    MotionStoppedEvent,
    LowBatteryEvent,
    CameraOfflineEvent,
    SystemErrorEvent,
)


def test_motion_detected_event():
    """Test motion detected event creation"""
    event = MotionDetectedEvent(
        device_sn="T8600P1234567890",
        video_url="http://example.com/video.mp4"
    )

    assert event.event == "motion_detected"
    assert event.device_sn == "T8600P1234567890"
    assert event.video_url == "http://example.com/video.mp4"
    assert event.video_status == "recording"
    assert isinstance(event.timestamp, datetime)


def test_motion_stopped_event():
    """Test motion stopped event creation"""
    event = MotionStoppedEvent(
        device_sn="T8600P1234567890",
        video_url="http://example.com/video.mp4",
        duration_seconds=120
    )

    assert event.event == "motion_stopped"
    assert event.device_sn == "T8600P1234567890"
    assert event.video_url == "http://example.com/video.mp4"
    assert event.video_status == "completed"
    assert event.duration_seconds == 120
    assert isinstance(event.timestamp, datetime)


def test_low_battery_event():
    """Test low battery event creation"""
    event = LowBatteryEvent(
        device_sn="T8600P1234567890",
        battery_level=15
    )

    assert event.event == "low_battery"
    assert event.device_sn == "T8600P1234567890"
    assert event.battery_level == 15
    assert isinstance(event.timestamp, datetime)


def test_low_battery_event_without_level():
    """Test low battery event without battery level"""
    event = LowBatteryEvent(
        device_sn="T8600P1234567890"
    )

    assert event.event == "low_battery"
    assert event.device_sn == "T8600P1234567890"
    assert event.battery_level is None


def test_camera_offline_event():
    """Test camera offline event creation"""
    event = CameraOfflineEvent(
        device_sn="T8600P1234567890",
        reason="connection_timeout"
    )

    assert event.event == "camera_offline"
    assert event.device_sn == "T8600P1234567890"
    assert event.reason == "connection_timeout"
    assert isinstance(event.timestamp, datetime)


def test_system_error_event():
    """Test system error event creation"""
    event = SystemErrorEvent(
        operation="webhook_send",
        error_type="ConnectionError",
        error_message="Failed to connect",
        retry_count=3,
        context={"url": "https://example.com"},
        traceback="Traceback..."
    )

    assert event.event == "system_error"
    assert event.operation == "webhook_send"
    assert event.error_type == "ConnectionError"
    assert event.error_message == "Failed to connect"
    assert event.retry_count == 3
    assert event.context == {"url": "https://example.com"}
    assert event.traceback == "Traceback..."
    assert isinstance(event.timestamp, datetime)


def test_event_serialization():
    """Test event can be serialized to dict/JSON"""
    event = MotionDetectedEvent(
        device_sn="T8600P1234567890",
        video_url="http://example.com/video.mp4"
    )

    data = event.model_dump()

    assert data["event"] == "motion_detected"
    assert data["device_sn"] == "T8600P1234567890"
    assert data["video_url"] == "http://example.com/video.mp4"
    assert data["video_status"] == "recording"
    assert "timestamp" in data
