"""FastAPI routes"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

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


