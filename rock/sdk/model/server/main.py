"""LLM Service - FastAPI server for sandbox communication."""

import argparse
import asyncio
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from rock.logger import init_logger
from rock.sdk.model.server.api.local import init_local_api, local_router
from rock.sdk.model.server.api.proxy import proxy_router
from rock.sdk.model.server.api.traces import traces_router
from rock.sdk.model.server.config import LOG_DIR, ModelServiceConfig
from rock.sdk.model.server.trace_store import init_store
from rock.sdk.model.server.utils import init_traj_file

# Configure logging
logger = init_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI, config: ModelServiceConfig):
    """Application lifespan context manager."""
    logger.info("LLM Service started")
    app.state.model_service_config = config

    # Initialize traj file override
    if config.trace_file_path:
        init_traj_file(config.trace_file_path)
        logger.info(f"Traj file path set to: {config.trace_file_path}")

    # Initialize trace store
    if config.trace_db_enabled:
        db_path = config.trace_db_path or os.path.join(LOG_DIR, "traces.db")
        store = init_store(db_path)
        app.state.trace_store = store
        logger.info(f"Trace store initialized at: {db_path}")

    yield
    logger.info("LLM Service shutting down")


def create_app(config: ModelServiceConfig) -> FastAPI:
    """Create FastAPI app with the given config."""
    app = FastAPI(
        title="LLM Service",
        description="Sandbox LLM Service for Agent and Roll communication",
        version="1.0.0",
        lifespan=lambda app: lifespan(app, config),
    )

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "healthy"}

    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        """Global exception handler."""
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": {"message": str(exc), "type": "internal_error", "code": "internal_error"}},
        )

    return app


def main(
    model_servie_type: str,
    config: ModelServiceConfig,
):
    """Run the LLM Service."""
    # Create app and add router
    app = create_app(config)
    if model_servie_type == "local":
        asyncio.run(init_local_api())
        app.include_router(local_router, prefix="", tags=["local"])
    else:
        app.include_router(proxy_router, prefix="", tags=["proxy"])

    if config.trace_db_enabled:
        app.include_router(traces_router, prefix="", tags=["traces"])

    logger.info(f"Starting LLM Service on {config.host}:{config.port}, type: {model_servie_type}")
    uvicorn.run(app, host=config.host, port=config.port, log_level="info", reload=False)


def create_config_from_args(args) -> ModelServiceConfig:
    """Create ModelServiceConfig from command line arguments."""
    # Build config from file or defaults
    if args.config_file:
        try:
            config = ModelServiceConfig.from_file(args.config_file)
            logger.info(f"Model Service Config loaded from: {args.config_file}")
        except Exception as e:
            logger.error(f"Failed to load config from {args.config_file}: {e}")
            raise e
    else:
        config = ModelServiceConfig()
        logger.info("No config file specified. Using default config settings.")

    # Command line arguments override config
    if args.host:
        config.host = args.host
        logger.info(f"host set from command line: {args.host}")
    if args.port:
        config.port = args.port
        logger.info(f"port set from command line: {args.port}")
    if args.proxy_base_url:
        config.proxy_base_url = args.proxy_base_url
        logger.info(f"proxy_base_url set from command line: {args.proxy_base_url}")
    if args.retryable_status_codes:
        codes = [int(c.strip()) for c in args.retryable_status_codes.split(",")]
        config.retryable_status_codes = codes
        logger.info(f"retryable_status_codes set from command line: {codes}")
    if args.request_timeout:
        config.request_timeout = args.request_timeout
        logger.info(f"request_timeout set from command line: {args.request_timeout}s")

    return config


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--type", type=str, choices=["local", "proxy"], default="local", help="Type of LLM service (local/proxy)"
    )
    parser.add_argument(
        "--config-file",
        type=str,
        default=None,
        help="Path to the configuration YAML file. If not set, default values will be used.",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Server host address. Overrides config file.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Server port. Overrides config file.",
    )
    parser.add_argument(
        "--proxy-base-url",
        type=str,
        default=None,
        help="Direct proxy base URL (e.g., https://your-endpoint.com/v1). Takes precedence over config file.",
    )
    parser.add_argument(
        "--retryable-status-codes",
        type=str,
        default=None,
        help="Retryable status codes, comma-separated (e.g., '429,500,502'). Overrides config file.",
    )
    parser.add_argument(
        "--request-timeout", type=int, default=None, help="Request timeout in seconds. Overrides config file."
    )
    args = parser.parse_args()

    config = create_config_from_args(args)
    main(args.type, config)
