"""FastAPI application entry point"""

import os
import sys
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import load_config
from src.utils.logger import setup_logger
from src.orchestrator import EventOrchestrator
from src.api.routes import router, set_orchestrator

# Global orchestrator instance
orchestrator: EventOrchestrator = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global orchestrator

    # Startup
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("Starting Eufy Security Python Integration v2.0.0")
    logger.info("=" * 60)

    try:
        # Load configuration
        config = load_config()

        # Setup logging
        setup_logger(
            name="",  # Root logger
            level=config.logging.level,
            log_format=config.logging.format,
            log_file=config.logging.file,
            max_size_mb=config.logging.max_size_mb,
            backup_count=config.logging.backup_count,
        )

        # Create orchestrator
        orchestrator = EventOrchestrator(config)

        # Set orchestrator in routes
        set_orchestrator(orchestrator)

        # Start orchestrator
        await orchestrator.start()

        logger.info("=" * 60)
        logger.info("✅ Application started successfully")
        logger.info(f"📡 Public URL: {config.server.public_url}")
        logger.info(f"📁 Storage: {config.recording.storage_path}")
        logger.info(f"⏱️  Retention: {config.recording.retention_days} days")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"❌ Failed to start application: {e}", exc_info=True)
        raise

    yield

    # Shutdown
    logger.info("=" * 60)
    logger.info("Shutting down gracefully...")
    logger.info("=" * 60)

    if orchestrator:
        await orchestrator.stop()

    logger.info("✅ Application stopped")


# Create FastAPI app
app = FastAPI(
    title="Eufy Security Integration",
    description="Eufy Security camera integration with Workato webhooks and video recording",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "Eufy Security Integration",
        "version": "2.0.0",
        "status": "running",
        "docs": "/docs",
    }


def main():
    """Main entry point"""
    # Get configuration from environment
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 10000))
    log_level = os.getenv("LOG_LEVEL", "info").lower()

    # Run uvicorn
    uvicorn.run(
        "src.main:app",
        host=host,
        port=port,
        log_level=log_level,
        access_log=True,
        reload=False,  # Don't use reload in production
    )


if __name__ == "__main__":
    main()