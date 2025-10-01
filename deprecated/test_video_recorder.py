"""Tests for video recorder service"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.services.video_recorder import VideoRecorder


@pytest.mark.asyncio
async def test_start_recording(mock_websocket_client, test_storage_path):
    """Test starting a video recording"""
    recorder = VideoRecorder(
        storage_path=str(test_storage_path),
        public_url_base="http://test.example.com",
        websocket_client=mock_websocket_client,
    )

    device_sn = "T8600P1234567890"

    with patch.object(recorder, '_start_ffmpeg_process') as mock_ffmpeg:
        mock_process = MagicMock()
        mock_ffmpeg.return_value = mock_process

        url = await recorder.start_recording(device_sn)

        # Verify WebSocket command was sent
        mock_websocket_client.send_command.assert_called_once_with(
            "device.start_livestream",
            {"serialNumber": device_sn}
        )

        # Verify recording is active
        assert recorder.is_recording(device_sn)

        # Verify URL format
        assert url.startswith("http://test.example.com/recordings/")
        assert device_sn in url
        assert url.endswith(".mp4")


@pytest.mark.asyncio
async def test_start_recording_already_active(mock_websocket_client, test_storage_path):
    """Test starting recording when already active returns existing URL"""
    recorder = VideoRecorder(
        storage_path=str(test_storage_path),
        public_url_base="http://test.example.com",
        websocket_client=mock_websocket_client,
    )

    device_sn = "T8600P1234567890"

    with patch.object(recorder, '_start_ffmpeg_process') as mock_ffmpeg:
        mock_process = MagicMock()
        mock_ffmpeg.return_value = mock_process

        # Start first recording
        url1 = await recorder.start_recording(device_sn)

        # Try to start again
        url2 = await recorder.start_recording(device_sn)

        # Should return same URL
        assert url1 == url2

        # Should only send command once
        assert mock_websocket_client.send_command.call_count == 1


@pytest.mark.asyncio
async def test_stop_recording(mock_websocket_client, test_storage_path):
    """Test stopping a video recording"""
    recorder = VideoRecorder(
        storage_path=str(test_storage_path),
        public_url_base="http://test.example.com",
        websocket_client=mock_websocket_client,
    )

    device_sn = "T8600P1234567890"

    with patch.object(recorder, '_start_ffmpeg_process') as mock_start, \
         patch.object(recorder, '_stop_ffmpeg_process') as mock_stop:

        mock_process = MagicMock()
        mock_start.return_value = mock_process

        # Start recording
        url = await recorder.start_recording(device_sn)

        # Stop recording
        result = await recorder.stop_recording(device_sn)

        assert result is not None
        stopped_url, duration = result

        # Verify URL matches
        assert stopped_url == url

        # Verify duration is reasonable (should be 0-1 seconds)
        assert 0 <= duration <= 2

        # Verify WebSocket command was sent
        mock_websocket_client.send_command.assert_called_with(
            "device.stop_livestream",
            {"serialNumber": device_sn}
        )

        # Verify recording is no longer active
        assert not recorder.is_recording(device_sn)

        # Verify ffmpeg was stopped
        mock_stop.assert_called_once()


@pytest.mark.asyncio
async def test_stop_recording_not_active(mock_websocket_client, test_storage_path):
    """Test stopping non-existent recording returns None"""
    recorder = VideoRecorder(
        storage_path=str(test_storage_path),
        public_url_base="http://test.example.com",
        websocket_client=mock_websocket_client,
    )

    result = await recorder.stop_recording("T8600P1234567890")

    assert result is None


@pytest.mark.asyncio
async def test_get_recording_info(mock_websocket_client, test_storage_path):
    """Test getting recording info"""
    recorder = VideoRecorder(
        storage_path=str(test_storage_path),
        public_url_base="http://test.example.com",
        websocket_client=mock_websocket_client,
    )

    device_sn = "T8600P1234567890"

    with patch.object(recorder, '_start_ffmpeg_process') as mock_ffmpeg:
        mock_process = MagicMock()
        mock_ffmpeg.return_value = mock_process

        # Start recording
        await recorder.start_recording(device_sn)

        # Get info
        info = recorder.get_recording_info(device_sn)

        assert info is not None
        assert info["device_sn"] == device_sn
        assert "filename" in info
        assert "public_url" in info
        assert "duration_seconds" in info
        assert "start_time" in info


@pytest.mark.asyncio
async def test_get_recording_info_not_active(mock_websocket_client, test_storage_path):
    """Test getting info for non-existent recording returns None"""
    recorder = VideoRecorder(
        storage_path=str(test_storage_path),
        public_url_base="http://test.example.com",
        websocket_client=mock_websocket_client,
    )

    info = recorder.get_recording_info("T8600P1234567890")

    assert info is None


@pytest.mark.asyncio
async def test_storage_path_created(mock_websocket_client, tmp_path):
    """Test storage path is created if it doesn't exist"""
    storage_path = tmp_path / "custom" / "recordings"

    assert not storage_path.exists()

    recorder = VideoRecorder(
        storage_path=str(storage_path),
        public_url_base="http://test.example.com",
        websocket_client=mock_websocket_client,
    )

    assert storage_path.exists()
