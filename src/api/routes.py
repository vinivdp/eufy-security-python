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


@router.get("/device/{device_sn}/commands")
async def get_device_commands(device_sn: str):
    """
    Get supported commands for a device

    Args:
        device_sn: Device serial number

    Returns:
        List of supported commands
    """
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Service not ready")

    try:
        response = await orchestrator.websocket_client.send_command(
            "device.get_commands",
            {"serialNumber": device_sn},
            wait_response=True,
            timeout=10.0
        )

        if response and response.get("success"):
            return {
                "device_sn": device_sn,
                "commands": response.get("result", {}).get("commands", [])
            }
        else:
            error_code = response.get("errorCode") if response else "no_response"
            raise HTTPException(
                status_code=400,
                detail=f"Failed to get commands: {error_code}"
            )

    except Exception as e:
        logger.error(f"Error getting commands for {device_sn}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


