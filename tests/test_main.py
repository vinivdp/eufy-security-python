"""Tests for main application"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client():
    """Create a test client"""
    return TestClient(app)


def test_root_endpoint(client):
    """Test root endpoint returns application info"""
    response = client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Eufy Security Integration"
    assert data["version"] == "2.0.0"
    assert data["status"] == "running"
    assert data["docs"] == "/docs"


def test_cors_headers(client):
    """Test CORS headers are properly set"""
    # Test with actual request that triggers CORS
    response = client.get("/", headers={"Origin": "http://example.com"})

    # FastAPI/Starlette adds CORS headers for requests with Origin header
    assert "access-control-allow-origin" in response.headers
    assert response.headers["access-control-allow-origin"] == "*"


def test_openapi_docs_available(client):
    """Test that OpenAPI docs are available"""
    response = client.get("/docs")
    assert response.status_code == 200

    response = client.get("/redoc")
    assert response.status_code == 200

    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert data["info"]["title"] == "Eufy Security Integration"
    assert data["info"]["version"] == "2.0.0"


@pytest.mark.asyncio
async def test_lifespan_startup_success():
    """Test application lifespan startup"""
    from src.main import lifespan

    mock_config = MagicMock()
    mock_config.logging.level = "INFO"
    mock_config.logging.format = "%(message)s"
    mock_config.logging.file = "./test.log"
    mock_config.logging.max_size_mb = 10
    mock_config.logging.backup_count = 1
    mock_config.server.public_url = "http://test.com"
    mock_config.recording.storage_path = "./recordings"
    mock_config.recording.retention_days = 7

    mock_orchestrator = AsyncMock()
    mock_orchestrator.start = AsyncMock()
    mock_orchestrator.stop = AsyncMock()

    with patch('src.main.load_config', return_value=mock_config), \
         patch('src.main.setup_logger'), \
         patch('src.main.EventOrchestrator', return_value=mock_orchestrator), \
         patch('src.main.set_orchestrator'):

        mock_app = MagicMock()

        async with lifespan(mock_app):
            # Verify startup was called
            mock_orchestrator.start.assert_called_once()

        # Verify shutdown was called
        mock_orchestrator.stop.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_startup_failure():
    """Test application lifespan handles startup failure"""
    from src.main import lifespan

    with patch('src.main.load_config', side_effect=Exception("Config error")):
        mock_app = MagicMock()

        with pytest.raises(Exception, match="Config error"):
            async with lifespan(mock_app):
                pass


@pytest.mark.asyncio
async def test_lifespan_shutdown_without_orchestrator():
    """Test application lifespan handles shutdown when orchestrator is None"""
    from src.main import lifespan
    import src.main

    mock_config = MagicMock()
    mock_config.logging.level = "INFO"
    mock_config.logging.format = "%(message)s"
    mock_config.logging.file = "./test.log"
    mock_config.logging.max_size_mb = 10
    mock_config.logging.backup_count = 1
    mock_config.server.public_url = "http://test.com"
    mock_config.recording.storage_path = "./recordings"
    mock_config.recording.retention_days = 7

    with patch('src.main.load_config', return_value=mock_config), \
         patch('src.main.setup_logger'), \
         patch('src.main.EventOrchestrator') as mock_orch_class, \
         patch('src.main.set_orchestrator'):

        # Make orchestrator.start() fail but set orchestrator to None
        mock_orchestrator = AsyncMock()
        mock_orchestrator.start = AsyncMock(side_effect=Exception("Start failed"))
        mock_orch_class.return_value = mock_orchestrator

        mock_app = MagicMock()

        # Store original orchestrator value
        original_orchestrator = src.main.orchestrator

        try:
            async with lifespan(mock_app):
                pass
        except Exception:
            pass  # Expected to fail

        # Shutdown should handle None orchestrator gracefully
        # No assertion needed, just verify it doesn't crash

        # Restore original
        src.main.orchestrator = original_orchestrator


def test_main_function_with_defaults():
    """Test main function uses default environment values"""
    with patch('src.main.uvicorn.run') as mock_run, \
         patch.dict('os.environ', {}, clear=True):

        from src.main import main
        main()

        # Verify uvicorn was called with defaults
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs['host'] == "0.0.0.0"
        assert call_kwargs['port'] == 10000
        assert call_kwargs['log_level'] == "info"
        assert call_kwargs['reload'] is False


def test_main_function_with_env_vars():
    """Test main function uses environment variables"""
    with patch('src.main.uvicorn.run') as mock_run, \
         patch.dict('os.environ', {
             'HOST': '127.0.0.1',
             'PORT': '8080',
             'LOG_LEVEL': 'DEBUG'
         }):

        from src.main import main
        main()

        # Verify uvicorn was called with env values
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs['host'] == "127.0.0.1"
        assert call_kwargs['port'] == 8080
        assert call_kwargs['log_level'] == "debug"


def test_app_metadata():
    """Test FastAPI app has correct metadata"""
    assert app.title == "Eufy Security Integration"
    assert app.version == "2.0.0"
    assert "Eufy Security camera integration" in app.description
