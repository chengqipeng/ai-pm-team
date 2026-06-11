"""持久化存储层 — PostgreSQL paas_ai schema"""

from .pg_pool import get_pool, close_pool
from .models import (
    Conversation, Message, MessageExt, Trace, TraceSpan,
    ContentReviewLog, TokenUsage,
)
from .dao import (
    ConversationDAO, MessageDAO, MessageExtDAO,
    TraceDAO, TraceSpanDAO, ContentReviewLogDAO, TokenUsageDAO,
)
from .memory_dao import MemoryDAO, MemoryRow
from .knowledge_models import (
    KnowledgeBaseRow,
    KnowledgeDatasetRow,
    KnowledgeSchemaRow,
    KnowledgeDocumentRow,
    KnowledgeSegmentRow,
    KnowledgeChunkRow,
    KnowledgeIngestQueueRow,
    KnowledgeIngestLogRow,
    KnowledgeSearchLogRow,
)
from .knowledge_dao import (
    KnowledgeBaseDAO,
    KnowledgeDatasetDAO,
    KnowledgeSchemaDAO,
    KnowledgeDocumentDAO,
    KnowledgeChunkDAO,
    KnowledgeIngestQueueDAO,
    KnowledgeIngestLogDAO,
    KnowledgeSearchLogDAO,
)
from .context_archive_models import ContextArchiveRow
from .context_archive_dao import ContextArchiveDAO

__all__ = [
    # pool
    "get_pool", "close_pool",
    # dialog models + DAOs
    "Conversation", "Message", "MessageExt", "Trace", "TraceSpan",
    "ContentReviewLog", "TokenUsage",
    "ConversationDAO", "MessageDAO", "MessageExtDAO",
    "TraceDAO", "TraceSpanDAO", "ContentReviewLogDAO", "TokenUsageDAO",
    # memory
    "MemoryDAO", "MemoryRow",
    # knowledge models
    "KnowledgeBaseRow", "KnowledgeDatasetRow",
    "KnowledgeSchemaRow", "KnowledgeDocumentRow",
    "KnowledgeSegmentRow",  # 内存 dataclass，无对应 PG 表
    "KnowledgeChunkRow", "KnowledgeIngestQueueRow",
    "KnowledgeIngestLogRow", "KnowledgeSearchLogRow",
    # knowledge DAOs
    "KnowledgeBaseDAO", "KnowledgeDatasetDAO",
    "KnowledgeSchemaDAO", "KnowledgeDocumentDAO",
    "KnowledgeChunkDAO", "KnowledgeIngestQueueDAO",
    "KnowledgeIngestLogDAO", "KnowledgeSearchLogDAO",
    # context archive
    "ContextArchiveRow", "ContextArchiveDAO",
]
