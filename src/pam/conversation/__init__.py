"""Conversation module — persistence, fact extraction, summarization."""

from pam.conversation.extraction import FactExtractionPipeline
from pam.conversation.service import ConversationService

__all__ = ["ConversationService", "FactExtractionPipeline"]
