"""Error logging models"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ErrorLog(BaseModel):
    """Error log entry"""
    operation: str
    error_type: str
    error_message: str
    retry_count: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    context: dict = Field(default_factory=dict)
    traceback: Optional[str] = None

    def to_webhook_payload(self) -> dict:
        """Convert to Workato webhook payload"""
        return {
            "event": "system_error",
            "operation": self.operation,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
            "traceback": self.traceback,
        }