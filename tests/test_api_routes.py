"""Tests for API routes"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from src.api.routes import router, set_orchestrator
from fastapi import FastAPI


@pytest.fixture
def test_app():
    """Create a test FastAPI app"""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(test_app):
    """Create a test client"""
    return TestClient(test_app)


@pytest.fixture
def mock_orchestrator_for_routes(mock_config):
    """Create a mock orchestrator for route testing"""
    orch = MagicMock()
    orch.config = mock_config
    orch.get_status = MagicMock(return_value={
        "running": True,
        "websocket_connected": True,
        "active_recordings": 2,
        "offline_devices": 0,
    })
    orch.storage_manager = MagicMock()
    orch.motion_handler = MagicMock()
    orch.offline_handler = MagicMock()
    orch.battery_handler = MagicMock()
    orch.error_logger = MagicMock()
    return orch


def test_health_check_without_orchestrator(client):
    """Test health check when orchestrator is not initialized"""
    set_orchestrator(None)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "initializing"
    assert response.json()["version"] == "2.0.0"


def test_health_check_with_orchestrator_running(client, mock_orchestrator_for_routes):
    """Test health check when orchestrator is running"""
    set_orchestrator(mock_orchestrator_for_routes)

    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "2.0.0"
    assert data["running"] is True
    assert data["websocket_connected"] is True
    assert data["active_recordings"] == 2


def test_health_check_with_orchestrator_stopped(client, mock_orchestrator_for_routes):
    """Test health check when orchestrator is stopped"""
    mock_orchestrator_for_routes.get_status.return_value = {
        "running": False,
        "websocket_connected": False,
        "active_recordings": 0,
        "offline_devices": 0,
    }
    set_orchestrator(mock_orchestrator_for_routes)

    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "stopped"


def test_serve_recording_success(client, mock_orchestrator_for_routes, tmp_path):
    """Test serving a recording file"""
    # Create a test video file
    video_file = tmp_path / "TEST123_20250130_143022.mp4"
    video_file.write_text("fake video content")

    mock_orchestrator_for_routes.config.recording.storage_path = str(tmp_path)
    set_orchestrator(mock_orchestrator_for_routes)

    response = client.get("/recordings/TEST123_20250130_143022.mp4")

    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert "Cache-Control" in response.headers
    assert "Accept-Ranges" in response.headers


def test_serve_recording_invalid_filename(client, mock_orchestrator_for_routes, tmp_path):
    """Test serving recording with invalid filename"""
    mock_orchestrator_for_routes.config.recording.storage_path = str(tmp_path)
    set_orchestrator(mock_orchestrator_for_routes)

    # Test path traversal attempt - FastAPI path params don't allow ../ so it's 404
    response = client.get("/recordings/..%2F..%2F..%2Fetc%2Fpasswd")
    # FastAPI normalizes the path, so this becomes a 404 not found
    assert response.status_code in [400, 404]

    # Test non-mp4 file
    response = client.get("/recordings/video.avi")
    assert response.status_code == 400


def test_serve_recording_not_found(client, mock_orchestrator_for_routes, tmp_path):
    """Test serving non-existent recording"""
    mock_orchestrator_for_routes.config.recording.storage_path = str(tmp_path)
    set_orchestrator(mock_orchestrator_for_routes)

    response = client.get("/recordings/nonexistent.mp4")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_serve_recording_without_orchestrator(client):
    """Test serving recording when orchestrator not ready"""
    set_orchestrator(None)

    response = client.get("/recordings/test.mp4")

    assert response.status_code == 503
    assert "not ready" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_recordings(client, mock_orchestrator_for_routes):
    """Test listing recordings"""
    mock_recordings = [
        {
            "filename": "TEST123_20250130_143022.mp4",
            "size": 1024000,
            "created": "2025-01-30T14:30:22",
        },
        {
            "filename": "TEST456_20250130_150000.mp4",
            "size": 2048000,
            "created": "2025-01-30T15:00:00",
        },
    ]

    mock_orchestrator_for_routes.storage_manager.list_recordings = AsyncMock(
        return_value=mock_recordings
    )
    set_orchestrator(mock_orchestrator_for_routes)

    response = client.get("/recordings")

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert len(data["recordings"]) == 2
    assert data["recordings"][0]["filename"] == "TEST123_20250130_143022.mp4"


@pytest.mark.asyncio
async def test_list_recordings_with_limit(client, mock_orchestrator_for_routes):
    """Test listing recordings with limit parameter"""
    mock_orchestrator_for_routes.storage_manager.list_recordings = AsyncMock(
        return_value=[]
    )
    set_orchestrator(mock_orchestrator_for_routes)

    response = client.get("/recordings?limit=10")

    assert response.status_code == 200
    mock_orchestrator_for_routes.storage_manager.list_recordings.assert_called_once_with(limit=10)


@pytest.mark.asyncio
async def test_get_storage_stats(client, mock_orchestrator_for_routes):
    """Test getting storage statistics"""
    mock_stats = {
        "total_space_gb": 100.0,
        "used_space_gb": 50.0,
        "free_space_gb": 50.0,
        "total_recordings": 42,
    }

    mock_orchestrator_for_routes.storage_manager.get_storage_stats = AsyncMock(
        return_value=mock_stats
    )
    set_orchestrator(mock_orchestrator_for_routes)

    response = client.get("/storage")

    assert response.status_code == 200
    data = response.json()
    assert data["total_space_gb"] == 100.0
    assert data["free_space_gb"] == 50.0
    assert data["total_recordings"] == 42


@pytest.mark.asyncio
async def test_get_devices_status(client, mock_orchestrator_for_routes):
    """Test getting devices status"""
    mock_orchestrator_for_routes.motion_handler.device_states = {
        "TEST123": MagicMock()
    }
    mock_orchestrator_for_routes.motion_handler.get_device_state = MagicMock(
        return_value={
            "device_sn": "TEST123",
            "is_recording": True,
            "video_url": "http://test.com/video.mp4",
        }
    )
    mock_orchestrator_for_routes.offline_handler.get_offline_devices = MagicMock(
        return_value=[]
    )
    mock_orchestrator_for_routes.battery_handler.get_battery_alerts = MagicMock(
        return_value=[]
    )

    set_orchestrator(mock_orchestrator_for_routes)

    response = client.get("/devices")

    assert response.status_code == 200
    data = response.json()
    assert "motion_states" in data
    assert "offline_devices" in data
    assert "battery_alerts" in data
    assert "TEST123" in data["motion_states"]


@pytest.mark.asyncio
async def test_get_recent_errors(client, mock_orchestrator_for_routes):
    """Test getting recent errors"""
    mock_errors = [
        {
            "timestamp": "2025-01-30T14:30:00",
            "operation": "webhook_send",
            "error": "Connection failed",
        }
    ]

    mock_orchestrator_for_routes.error_logger.get_recent_errors = MagicMock(
        return_value=mock_errors
    )
    set_orchestrator(mock_orchestrator_for_routes)

    response = client.get("/errors")

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert len(data["errors"]) == 1
    assert data["errors"][0]["operation"] == "webhook_send"


@pytest.mark.asyncio
async def test_get_recent_errors_with_limit(client, mock_orchestrator_for_routes):
    """Test getting recent errors with limit"""
    mock_orchestrator_for_routes.error_logger.get_recent_errors = MagicMock(
        return_value=[]
    )
    set_orchestrator(mock_orchestrator_for_routes)

    response = client.get("/errors?limit=20")

    assert response.status_code == 200
    mock_orchestrator_for_routes.error_logger.get_recent_errors.assert_called_once_with(limit=20)


@pytest.mark.asyncio
async def test_trigger_cleanup(client, mock_orchestrator_for_routes):
    """Test triggering manual storage cleanup"""
    mock_orchestrator_for_routes.storage_manager.cleanup_old_files = AsyncMock(
        return_value=5
    )
    mock_orchestrator_for_routes.storage_manager.ensure_free_space = AsyncMock(
        return_value=True
    )
    set_orchestrator(mock_orchestrator_for_routes)

    response = client.post("/cleanup")

    assert response.status_code == 200
    data = response.json()
    assert data["deleted_files"] == 5
    assert data["sufficient_space"] is True


def test_endpoints_without_orchestrator(client):
    """Test that endpoints return 503 when orchestrator is not set"""
    set_orchestrator(None)

    endpoints = [
        ("/storage", "get"),
        ("/devices", "get"),
        ("/errors", "get"),
        ("/cleanup", "post"),
    ]

    for endpoint, method in endpoints:
        if method == "get":
            response = client.get(endpoint)
        else:
            response = client.post(endpoint)

        assert response.status_code == 503
        assert "not ready" in response.json()["detail"].lower()
