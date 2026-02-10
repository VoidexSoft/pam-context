"""Documents endpoint — list and view ingested documents."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pam.api.deps import get_db
from pam.ingestion.stores.postgres_store import PostgresStore

router = APIRouter()


@router.get("/documents")
async def list_documents(
    db: AsyncSession = Depends(get_db),
):
    """List all ingested documents with segment counts."""
    store = PostgresStore(db)
    return await store.list_documents()
