"""Tests for the entity type taxonomy defined in pam.graph.entity_types."""

from pydantic import BaseModel

from pam.graph.entity_types import ENTITY_TYPES

# Fields that Graphiti reserves on node objects -- entity type models must not
# declare any of these as their own attributes.
GRAPHITI_PROTECTED_FIELDS = frozenset({
    "uuid",
    "name",
    "group_id",
    "labels",
    "created_at",
    "summary",
    "attributes",
    "name_embedding",
})

EXPECTED_TYPES = {"Person", "Team", "Project", "Technology", "Process", "Concept", "Asset"}


class TestEntityTypeRegistry:
    def test_entity_types_has_seven_entries(self):
        assert len(ENTITY_TYPES) == 7

    def test_all_expected_type_names_exist(self):
        assert set(ENTITY_TYPES.keys()) == EXPECTED_TYPES

    def test_all_values_are_basemodel_subclasses(self):
        for name, model_cls in ENTITY_TYPES.items():
            assert issubclass(model_cls, BaseModel), f"{name} is not a BaseModel subclass"

    def test_no_model_uses_protected_field_names(self):
        for name, model_cls in ENTITY_TYPES.items():
            model_fields = set(model_cls.model_fields.keys())
            overlap = model_fields & GRAPHITI_PROTECTED_FIELDS
            assert not overlap, f"{name} uses Graphiti protected fields: {overlap}"

    def test_each_model_instantiates_with_no_arguments(self):
        for name, model_cls in ENTITY_TYPES.items():
            instance = model_cls()
            assert instance is not None, f"{name}() raised or returned None"

    def test_each_model_instantiates_with_all_fields(self):
        """Each model can be populated with string values for all declared fields."""
        for name, model_cls in ENTITY_TYPES.items():
            field_values = {}
            for field_name, field_info in model_cls.model_fields.items():
                # Use a sensible default based on annotation
                annotation = field_info.annotation
                if annotation is int or annotation == (int | None):
                    field_values[field_name] = 42
                else:
                    field_values[field_name] = f"test-{field_name}"
            instance = model_cls(**field_values)
            for field_name, value in field_values.items():
                assert getattr(instance, field_name) == value, (
                    f"{name}.{field_name} did not round-trip"
                )
