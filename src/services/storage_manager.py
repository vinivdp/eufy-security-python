"""Storage management service"""

import asyncio
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


class StorageManager:
    """
    Storage management for recorded videos

    Handles cleanup of old files and disk space monitoring
    """

    def __init__(
        self,
        storage_path: str,
        retention_days: int = 90,
        min_free_space_gb: int = 5,
    ):
        """
        Initialize storage manager

        Args:
            storage_path: Path to recordings directory
            retention_days: Number of days to keep recordings
            min_free_space_gb: Minimum free space in GB (triggers cleanup)
        """
        self.storage_path = Path(storage_path)
        self.retention_days = retention_days
        self.min_free_space_bytes = min_free_space_gb * 1024**3

        # Ensure storage directory exists
        self.storage_path.mkdir(parents=True, exist_ok=True)

    async def cleanup_old_files(self) -> int:
        """
        Delete files older than retention_days

        Returns:
            Number of files deleted
        """
        logger.info(f"Running cleanup: deleting files older than {self.retention_days} days")

        cutoff_date = datetime.now() - timedelta(days=self.retention_days)
        deleted_count = 0

        for filepath in self.storage_path.glob("*.mp4"):
            try:
                # Get file modification time
                mtime = datetime.fromtimestamp(filepath.stat().st_mtime)

                if mtime < cutoff_date:
                    file_size_mb = filepath.stat().st_size / (1024**2)
                    filepath.unlink()
                    deleted_count += 1
                    logger.info(f"🗑️  Deleted old file: {filepath.name} ({file_size_mb:.1f} MB)")

            except Exception as e:
                logger.error(f"Error deleting file {filepath}: {e}")

        logger.info(f"Cleanup complete: {deleted_count} files deleted")
        return deleted_count

    async def check_disk_space(self) -> tuple[int, int, float]:
        """
        Check available disk space

        Returns:
            Tuple of (total_bytes, used_bytes, usage_percent)
        """
        stat = shutil.disk_usage(self.storage_path)
        usage_percent = (stat.used / stat.total) * 100

        logger.debug(
            f"Disk space: {stat.used / 1024**3:.1f}GB / {stat.total / 1024**3:.1f}GB "
            f"({usage_percent:.1f}% used)"
        )

        return stat.total, stat.used, usage_percent

    async def ensure_free_space(self) -> bool:
        """
        Ensure minimum free space is available

        Deletes oldest files if necessary

        Returns:
            True if sufficient space is available, False otherwise
        """
        stat = shutil.disk_usage(self.storage_path)

        if stat.free >= self.min_free_space_bytes:
            return True

        logger.warning(
            f"Low disk space: {stat.free / 1024**3:.1f}GB free "
            f"(minimum: {self.min_free_space_bytes / 1024**3:.1f}GB)"
        )

        # Get all video files sorted by modification time (oldest first)
        files = sorted(
            self.storage_path.glob("*.mp4"),
            key=lambda f: f.stat().st_mtime,
        )

        deleted_count = 0
        freed_space = 0

        for filepath in files:
            try:
                file_size = filepath.stat().st_size
                filepath.unlink()
                deleted_count += 1
                freed_space += file_size

                logger.info(
                    f"🗑️  Deleted to free space: {filepath.name} "
                    f"({file_size / 1024**2:.1f} MB)"
                )

                # Check if we have enough space now
                stat = shutil.disk_usage(self.storage_path)
                if stat.free >= self.min_free_space_bytes:
                    logger.info(
                        f"Freed {freed_space / 1024**3:.1f}GB by deleting {deleted_count} files"
                    )
                    return True

            except Exception as e:
                logger.error(f"Error deleting file {filepath}: {e}")

        logger.error("Failed to free sufficient disk space")
        return False

    async def get_storage_stats(self) -> dict:
        """
        Get storage statistics

        Returns:
            Dictionary with storage stats
        """
        files = list(self.storage_path.glob("*.mp4"))
        total_size = sum(f.stat().st_size for f in files)

        stat = shutil.disk_usage(self.storage_path)

        return {
            "total_files": len(files),
            "total_size_gb": total_size / 1024**3,
            "disk_total_gb": stat.total / 1024**3,
            "disk_used_gb": stat.used / 1024**3,
            "disk_free_gb": stat.free / 1024**3,
            "disk_usage_percent": (stat.used / stat.total) * 100,
            "retention_days": self.retention_days,
        }

    async def list_recordings(self, limit: int = 50) -> List[dict]:
        """
        List recent recordings

        Args:
            limit: Maximum number of recordings to return

        Returns:
            List of recording info dictionaries
        """
        files = sorted(
            self.storage_path.glob("*.mp4"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )[:limit]

        recordings = []
        for filepath in files:
            stat = filepath.stat()
            recordings.append({
                "filename": filepath.name,
                "size_mb": stat.st_size / 1024**2,
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })

        return recordings

    async def start_scheduled_cleanup(self, interval_hours: int = 24) -> None:
        """
        Start scheduled cleanup task

        Args:
            interval_hours: Interval between cleanups in hours
        """
        logger.info(f"Starting scheduled cleanup (every {interval_hours} hours)")

        while True:
            try:
                await asyncio.sleep(interval_hours * 3600)
                await self.cleanup_old_files()
                await self.ensure_free_space()
            except Exception as e:
                logger.error(f"Error in scheduled cleanup: {e}", exc_info=True)