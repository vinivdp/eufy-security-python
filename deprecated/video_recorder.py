"""Video recording service"""

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict
import subprocess

logger = logging.getLogger(__name__)


class VideoRecorder:
    """
    Video recorder for capturing livestreams from eufy cameras

    Records unchunked video files using ffmpeg
    """

    def __init__(
        self,
        storage_path: str,
        public_url_base: str,
        websocket_client: "WebSocketClient",
        video_codec: str = "libx264",
        video_quality: str = "medium",
    ):
        """
        Initialize video recorder

        Args:
            storage_path: Path to store recordings
            public_url_base: Base URL for public access (e.g., https://app.onrender.com)
            websocket_client: WebSocketClient instance
            video_codec: Video codec (default: libx264)
            video_quality: Quality preset (low, medium, high)
        """
        self.storage_path = Path(storage_path)
        self.public_url_base = public_url_base.rstrip("/")
        self.websocket_client = websocket_client
        self.video_codec = video_codec
        self.video_quality = video_quality

        # Active recordings: device_sn -> (filename, process, start_time)
        self.active_recordings: Dict[str, tuple[str, subprocess.Popen, datetime]] = {}

        # Ensure storage directory exists
        self.storage_path.mkdir(parents=True, exist_ok=True)

    async def start_recording(self, device_sn: str) -> str:
        """
        Start recording for a device

        Args:
            device_sn: Device serial number

        Returns:
            Public URL of the recording

        Raises:
            RuntimeError: If recording is already active for this device
        """
        if device_sn in self.active_recordings:
            logger.warning(f"Recording already active for {device_sn}")
            filename, _, _ = self.active_recordings[device_sn]
            return self._get_public_url(filename)

        # Generate filename: {device_sn}_{YYYYMMDD_HHMMSS}.mp4
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{device_sn}_{timestamp}.mp4"
        filepath = self.storage_path / filename

        logger.info(f"🎥 Starting recording for {device_sn}: {filename}")

        # Send start livestream command
        try:
            await self.websocket_client.send_command(
                "device.start_livestream", {"serialNumber": device_sn}
            )
        except Exception as e:
            logger.error(f"Failed to start livestream for {device_sn}: {e}")
            raise

        # Start ffmpeg process (will receive data via stdin)
        # Note: In actual implementation, we'd pipe livestream data to ffmpeg
        # For now, we'll create a placeholder process
        process = await self._start_ffmpeg_process(filepath)

        # Store active recording
        self.active_recordings[device_sn] = (filename, process, datetime.now())

        # Return public URL immediately
        public_url = self._get_public_url(filename)
        logger.info(f"📡 Recording started: {public_url}")

        return public_url

    async def stop_recording(self, device_sn: str) -> Optional[tuple[str, int]]:
        """
        Stop recording for a device

        Args:
            device_sn: Device serial number

        Returns:
            Tuple of (public_url, duration_seconds) if recording was active, None otherwise
        """
        if device_sn not in self.active_recordings:
            logger.warning(f"No active recording for {device_sn}")
            return None

        filename, process, start_time = self.active_recordings[device_sn]

        logger.info(f"⏹️  Stopping recording for {device_sn}: {filename}")

        # Send stop livestream command
        try:
            await self.websocket_client.send_command(
                "device.stop_livestream", {"serialNumber": device_sn}
            )
        except Exception as e:
            logger.error(f"Failed to stop livestream for {device_sn}: {e}")

        # Stop ffmpeg process
        await self._stop_ffmpeg_process(process)

        # Calculate duration
        duration_seconds = int((datetime.now() - start_time).total_seconds())

        # Remove from active recordings
        del self.active_recordings[device_sn]

        public_url = self._get_public_url(filename)
        logger.info(f"✅ Recording stopped: {public_url} (duration: {duration_seconds}s)")

        return public_url, duration_seconds

    async def write_livestream_data(self, device_sn: str, data: bytes, is_video: bool = True) -> None:
        """
        Write livestream data to ffmpeg process

        Args:
            device_sn: Device serial number
            data: Video/audio data bytes
            is_video: True for video data, False for audio data
        """
        if device_sn not in self.active_recordings:
            logger.warning(f"Received {'video' if is_video else 'audio'} data for inactive recording: {device_sn}")
            return

        _, process, _ = self.active_recordings[device_sn]

        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.write(data)
                process.stdin.flush()  # Ensure data is sent immediately
                await asyncio.sleep(0)  # Yield control
            else:
                logger.warning(f"ffmpeg stdin closed for {device_sn}")
        except BrokenPipeError:
            logger.error(f"ffmpeg process died for {device_sn}")
            # Clean up dead recording
            if device_sn in self.active_recordings:
                del self.active_recordings[device_sn]
        except Exception as e:
            logger.error(f"Error writing to ffmpeg for {device_sn}: {e}")

    def is_recording(self, device_sn: str) -> bool:
        """Check if recording is active for device"""
        return device_sn in self.active_recordings

    def get_recording_info(self, device_sn: str) -> Optional[Dict]:
        """Get info about active recording"""
        if device_sn not in self.active_recordings:
            return None

        filename, _, start_time = self.active_recordings[device_sn]
        duration = int((datetime.now() - start_time).total_seconds())

        return {
            "device_sn": device_sn,
            "filename": filename,
            "public_url": self._get_public_url(filename),
            "duration_seconds": duration,
            "start_time": start_time.isoformat(),
        }

    def _get_public_url(self, filename: str) -> str:
        """Generate public URL for recording"""
        return f"{self.public_url_base}/recordings/{filename}"

    async def _start_ffmpeg_process(self, filepath: Path) -> subprocess.Popen:
        """
        Start ffmpeg process for recording

        Note: This is a simplified implementation. In production, you'd:
        1. Receive livestream data from WebSocket events
        2. Pipe it to ffmpeg stdin
        3. Use proper codec settings based on camera stream format
        """
        quality_presets = {
            "low": "ultrafast",
            "medium": "medium",
            "high": "slow",
        }
        preset = quality_presets.get(self.video_quality, "medium")

        # FFmpeg command to read from stdin and write to file
        cmd = [
            "ffmpeg",
            "-i", "pipe:0",  # Read from stdin
            "-c:v", self.video_codec,
            "-preset", preset,
            "-c:a", "aac",
            "-f", "mp4",
            "-movflags", "frag_keyframe+empty_moov",  # Enable streaming
            str(filepath),
        ]

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        logger.debug(f"FFmpeg process started: PID {process.pid}")
        return process

    async def _stop_ffmpeg_process(self, process: subprocess.Popen) -> None:
        """Stop ffmpeg process gracefully"""
        try:
            # Close stdin to signal EOF
            if process.stdin:
                process.stdin.close()

            # Wait for process to finish (with timeout)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("FFmpeg didn't stop gracefully, terminating")
                process.terminate()
                process.wait(timeout=5)

            logger.debug(f"FFmpeg process stopped: PID {process.pid}")

        except Exception as e:
            logger.error(f"Error stopping ffmpeg: {e}")
            process.kill()  # Force kill as last resort