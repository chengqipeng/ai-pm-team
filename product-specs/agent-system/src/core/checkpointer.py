"""Checkpointer — SQLite 本地 + Redis 异步持久化

生产环境使用 Redis（AsyncRedisSaver），复用 neo-apps-ai-agent-service 的连接配置。
开发环境使用 SQLite（SqliteSaver）。
"""
from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

logger = logging.getLogger(__name__)


def _mask_url(url: str) -> str:
    """脱敏 Redis URL 中的密码"""
    if ":" in url and "@" in url:
        # redis://:password@host:port → redis://:***@host:port
        prefix, rest = url.split("@", 1)
        return prefix.rsplit(":", 1)[0] + ":***@" + rest
    return url


# neo-apps-ai-agent-service 的 Redis 连接配置
# 来源: resources/redis/redis.yml → redis.host 字段
# 环境变量 AI_REDIS_URL 可覆盖，默认值为线上内网地址
DEFAULT_REDIS_URL = os.environ.get(
    "AI_REDIS_URL",
    "redis://:ingage@10.60.60.21:6379",
)


def create_checkpointer(backend: str = "sqlite", **kwargs) -> BaseCheckpointSaver | None:
    """创建同步 Checkpointer 实例（开发环境用）

    Args:
        backend: "sqlite" 或 "redis"
        **kwargs: 后端特定参数（db_path / redis_url）
    """
    if backend == "sqlite":
        db_path = kwargs.get("db_path", "./data/checkpoints.db")
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
            conn = sqlite3.connect(db_path, check_same_thread=False)
            saver = SqliteSaver(conn)
            saver.setup()
            logger.info("SQLite checkpointer created: %s", db_path)
            return saver
        except Exception:
            logger.warning("SQLite checkpointer creation failed", exc_info=True)
            return None

    elif backend == "redis":
        redis_url = kwargs.get("redis_url", DEFAULT_REDIS_URL)
        try:
            from langgraph.checkpoint.redis import RedisSaver
            saver = RedisSaver.from_conn_string(redis_url)
            saver.setup()
            logger.info("Redis checkpointer created (sync)")
            return saver
        except Exception:
            logger.warning("Redis sync checkpointer failed", exc_info=True)
            return None

    logger.warning("Unknown checkpointer backend: %s", backend)
    return None


async def create_async_redis_checkpointer(
    redis_url: str | None = None,
    ttl_minutes: int = 24 * 60,
) -> BaseCheckpointSaver | None:
    """创建异步 Redis Checkpointer（生产环境用）

    复用 neo-apps-ai-agent-service 的 Redis 连接方式：
    1. 优先使用传入的 redis_url
    2. 其次尝试 common.utils.redis_config.get_redis_config()（线上 Apollo 配置）
    3. 最后 fallback 到环境变量 REDIS_URL

    Args:
        redis_url: Redis 连接地址，格式 redis://host:port
        ttl_minutes: 检查点 TTL（分钟），默认 24 小时
    """
    # 解析 Redis URL
    url = redis_url
    if not url:
        # 尝试从 neo-apps 的公共配置获取（线上环境，依赖 neo_ai_infr_basic）
        try:
            from common.utils.redis_config import get_redis_config
            config = get_redis_config()
            url = config.get("redis", {}).get("host", "")
            logger.info("Redis URL from neo-apps config: %s", _mask_url(url))
        except ImportError:
            # 不在 neo-apps 环境中，使用默认地址
            pass
    if not url:
        url = DEFAULT_REDIS_URL
        logger.info("Redis URL from default: %s", _mask_url(url))

    if not url:
        logger.warning("Redis URL not available, checkpointer disabled")
        return None

    try:
        from langgraph.checkpoint.redis import AsyncRedisSaver

        ttl_config = {
            "default_ttl": ttl_minutes,
            "refresh_on_read": True,
        }
        # 直接构造实例（不用 from_conn_string 上下文管理器），
        # 避免连接被提前关闭导致后续请求 "Connection closed by server"
        checkpointer = AsyncRedisSaver(redis_url=url, ttl=ttl_config)
        await checkpointer.asetup()
        logger.info("Async Redis checkpointer created: ttl=%d min", ttl_minutes)
        return checkpointer
    except ImportError:
        logger.warning("langgraph.checkpoint.redis not installed, run: pip install langgraph-checkpoint-redis")
        return None
    except Exception:
        logger.warning("Async Redis checkpointer failed, Agent 状态不会持久化", exc_info=True)
        return None
