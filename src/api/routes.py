"""FastAPI routes"""

import os
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# Global orchestrator reference (set by main.py)
orchestrator: Optional["EventOrchestrator"] = None


def set_orchestrator(orch: "EventOrchestrator") -> None:
    """Set global orchestrator reference"""
    global orchestrator
    orchestrator = orch


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    if not orchestrator:
        return JSONResponse(
            status_code=503,
            content={"status": "initializing", "version": "2.0.0"}
        )

    status = orchestrator.get_status()

    return {
        "status": "ok" if status["running"] else "stopped",
        "version": "2.0.0",
        **status
    }


@router.get("/recordings/{filename}")
async def serve_recording(filename: str):
    """
    Serve video recording file

    Args:
        filename: Video filename (e.g., T8600P2323209876_20250130_143022.mp4)

    Returns:
        Video file with proper headers
    """
    # Validate filename format (basic security)
    if not filename.endswith(".mp4") or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not orchestrator:
        raise HTTPException(status_code=503, detail="Service not ready")

    # Get file path
    storage_path = Path(orchestrator.config.recording.storage_path)
    file_path = storage_path / filename

    # Check if file exists
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Recording not found")

    # Check if file is readable
    if not file_path.is_file():
        raise HTTPException(status_code=400, detail="Invalid file")

    logger.info(f"Serving recording: {filename}")

    # Serve file with appropriate headers
    return FileResponse(
        file_path,
        media_type="video/mp4",
        headers={
            "Cache-Control": "public, max-age=604800",  # Cache for 7 days
            "Accept-Ranges": "bytes",  # Enable video seeking
        },
        filename=filename,
    )


@router.get("/recordings")
async def list_recordings(limit: int = Query(50, le=100)):
    """
    List recent recordings

    Args:
        limit: Maximum number of recordings to return (max 100)

    Returns:
        List of recording metadata
    """
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Service not ready")

    recordings = await orchestrator.storage_manager.list_recordings(limit=limit)

    return {
        "count": len(recordings),
        "recordings": recordings
    }


@router.get("/storage")
async def get_storage_stats():
    """Get storage statistics"""
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Service not ready")

    stats = await orchestrator.storage_manager.get_storage_stats()

    return stats


@router.get("/devices")
async def get_devices_status():
    """Get status of all devices"""
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Service not ready")

    # Get motion states
    motion_states = {}
    for device_sn in orchestrator.motion_handler.device_states:
        state = orchestrator.motion_handler.get_device_state(device_sn)
        if state:
            motion_states[device_sn] = state

    # Get offline devices
    offline_devices = orchestrator.offline_handler.get_offline_devices()

    # Get battery alerts
    battery_alerts = orchestrator.battery_handler.get_battery_alerts()

    return {
        "motion_states": motion_states,
        "offline_devices": offline_devices,
        "battery_alerts": battery_alerts,
    }


@router.get("/errors")
async def get_recent_errors(limit: int = Query(10, le=50)):
    """
    Get recent error logs (for debugging)

    Args:
        limit: Maximum number of errors to return (max 50)

    Returns:
        List of recent errors
    """
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Service not ready")

    errors = orchestrator.error_logger.get_recent_errors(limit=limit)

    return {
        "count": len(errors),
        "errors": errors
    }


@router.post("/cleanup")
async def trigger_cleanup():
    """Manually trigger storage cleanup"""
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Service not ready")

    deleted_count = await orchestrator.storage_manager.cleanup_old_files()
    space_ok = await orchestrator.storage_manager.ensure_free_space()

    return {
        "deleted_files": deleted_count,
        "sufficient_space": space_ok,
    }