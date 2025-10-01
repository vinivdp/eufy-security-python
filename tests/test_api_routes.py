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
        "offline_devices": 0,
    })
    orch.motion_handler = MagicMock()
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


def test_health_check_with_orchestrator_stopped(client, mock_orchestrator_for_routes):
    """Test health check when orchestrator is stopped"""
    mock_orchestrator_for_routes.get_status.return_value = {
        "running": False,
        "websocket_connected": False,
        "offline_devices": 0,
    }
    set_orchestrator(mock_orchestrator_for_routes)

    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "stopped"


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


def test_endpoints_without_orchestrator(client):
    """Test that endpoints return 503 when orchestrator is not set"""
    set_orchestrator(None)

    endpoints = [
        ("/errors", "get"),
    ]

    for endpoint, method in endpoints:
        if method == "get":
            response = client.get(endpoint)
        else:
            response = client.post(endpoint)

        assert response.status_code == 503
        assert "not ready" in response.json()["detail"].lower()
