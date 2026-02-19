"""Entity type taxonomy for the PAM knowledge graph.

Defines 7 Pydantic models representing the core entity categories in a game studio
domain. These models are used as Graphiti's ``entity_types`` parameter when adding
episodes, allowing the graph to classify extracted entities automatically.

All fields are optional (``None`` default) because Graphiti populates attributes
on a best-effort basis from unstructured text.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Person(BaseModel):
    """A person referenced in business documents -- team members, stakeholders, executives."""

    role: str | None = Field(None, description="Job title or functional role")
    department: str | None = Field(None, description="Department or business unit")


class Team(BaseModel):
    """An organizational unit -- squads, departments, working groups."""

    team_type: str | None = Field(None, description="Type of team (e.g. squad, department, committee)")
    size: int | None = Field(None, description="Approximate headcount")


class Project(BaseModel):
    """A project, product, or initiative being tracked."""

    project_type: str | None = Field(None, description="Type of project (e.g. game, tool, platform)")
    status: str | None = Field(None, description="Current status (e.g. active, completed, on-hold)")
    platform: str | None = Field(None, description="Target platform (e.g. PC, console, mobile)")


class Technology(BaseModel):
    """A technology, tool, or software system used by the organization."""

    tech_category: str | None = Field(None, description="Category (e.g. engine, framework, service)")
    version: str | None = Field(None, description="Version identifier if known")


class Process(BaseModel):
    """A business process, workflow, or standard operating procedure."""

    process_type: str | None = Field(None, description="Type of process (e.g. review, deployment, hiring)")
    frequency: str | None = Field(None, description="How often the process runs (e.g. weekly, on-demand)")


class Concept(BaseModel):
    """An abstract concept, methodology, or domain term."""

    concept_type: str | None = Field(None, description="Category (e.g. methodology, metric, principle)")
    maturity: str | None = Field(None, description="Maturity level (e.g. emerging, established, deprecated)")


class Asset(BaseModel):
    """A tangible or digital asset -- documents, repositories, datasets, builds."""

    asset_type: str | None = Field(None, description="Type of asset (e.g. document, repo, dataset, build)")
    format: str | None = Field(None, description="File format or medium (e.g. PDF, Confluence, Git)")


ENTITY_TYPES: dict[str, type[BaseModel]] = {
    "Person": Person,
    "Team": Team,
    "Project": Project,
    "Technology": Technology,
    "Process": Process,
    "Concept": Concept,
    "Asset": Asset,
}
