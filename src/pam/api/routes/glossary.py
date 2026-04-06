"""Glossary CRUD REST endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from pam.api.auth import get_current_user
from pam.api.rate_limit import limiter
from pam.common.config import settings
from pam.common.models import (
    GlossaryResolveResult,
    GlossarySearchResult,
    GlossaryTermCreate,
    GlossaryTermResponse,
    GlossaryTermUpdate,
    User,
)

router = APIRouter()


def get_glossary_service():
    """Dependency stub -- overridden at app startup."""
    raise RuntimeError("GlossaryService not initialized")


@router.post("", response_model=GlossaryTermResponse, status_code=201)
@limiter.limit(settings.rate_limit_default)
async def add_term(
    request: Request,  # noqa: ARG001
    body: GlossaryTermCreate,
    glossary_service=Depends(get_glossary_service),
    _user: User | None = Depends(get_current_user),
):
    """Add a new glossary term.

    Returns 409 if a semantically similar term already exists.
    """
    try:
        return await glossary_service.add(
            canonical=body.canonical,
            aliases=body.aliases,
            definition=body.definition,
            category=body.category,
            metadata=body.metadata,
            project_id=body.project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/search", response_model=list[GlossarySearchResult])
@limiter.limit(settings.rate_limit_search)
async def search_terms(
    request: Request,  # noqa: ARG001
    query: str,
    project_id: uuid.UUID | None = None,
    category: str | None = None,
    top_k: int = Query(default=10, ge=1, le=50),
    glossary_service=Depends(get_glossary_service),
    _user: User | None = Depends(get_current_user),
):
    """Semantic search across glossary terms."""
    return await glossary_service.search(
        query=query,
        project_id=project_id,
        category=category,
        top_k=top_k,
    )


@router.post("/resolve", response_model=GlossaryResolveResult)
@limiter.limit(settings.rate_limit_search)
async def resolve_aliases(
    request: Request,  # noqa: ARG001
    query: str,
    project_id: uuid.UUID | None = None,
    glossary_service=Depends(get_glossary_service),
    _user: User | None = Depends(get_current_user),
):
    """Resolve aliases in a query string to canonical glossary terms.

    Returns the expanded query with resolved terms noted.
    """
    from pam.glossary.resolver import AliasResolver

    resolver = AliasResolver(
        store=glossary_service._store,
        project_id=project_id,
    )
    result = await resolver.resolve(query=query, project_id=project_id)
    return GlossaryResolveResult(
        original_query=result.original_query,
        expanded_query=result.expanded_query,
        resolved_terms=result.resolved_terms,
    )


@router.get("", response_model=list[GlossaryTermResponse])
@limiter.limit(settings.rate_limit_default)
async def list_terms(
    request: Request,  # noqa: ARG001
    project_id: uuid.UUID | None = None,
    category: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    glossary_service=Depends(get_glossary_service),
    _user: User | None = Depends(get_current_user),
):
    """List glossary terms, optionally filtered by project and category."""
    return await glossary_service.list_terms(
        project_id=project_id,
        category=category,
        limit=limit,
        offset=offset,
    )


@router.get("/{term_id}", response_model=GlossaryTermResponse)
@limiter.limit(settings.rate_limit_default)
async def get_term(
    request: Request,  # noqa: ARG001
    term_id: uuid.UUID,
    glossary_service=Depends(get_glossary_service),
    _user: User | None = Depends(get_current_user),
):
    """Get a specific glossary term by ID."""
    result = await glossary_service.get(term_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Glossary term not found")
    return result


@router.patch("/{term_id}", response_model=GlossaryTermResponse)
@limiter.limit(settings.rate_limit_default)
async def update_term(
    request: Request,  # noqa: ARG001
    term_id: uuid.UUID,
    body: GlossaryTermUpdate,
    glossary_service=Depends(get_glossary_service),
    _user: User | None = Depends(get_current_user),
):
    """Update a glossary term's fields."""
    result = await glossary_service.update(
        term_id=term_id,
        canonical=body.canonical,
        aliases=body.aliases,
        definition=body.definition,
        category=body.category,
        metadata=body.metadata,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Glossary term not found")
    return result


@router.delete("/{term_id}")
@limiter.limit(settings.rate_limit_default)
async def delete_term(
    request: Request,  # noqa: ARG001
    term_id: uuid.UUID,
    glossary_service=Depends(get_glossary_service),
    _user: User | None = Depends(get_current_user),
):
    """Delete a glossary term."""
    deleted = await glossary_service.delete(term_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Glossary term not found")
    return {"message": "Glossary term deleted", "id": str(term_id)}
