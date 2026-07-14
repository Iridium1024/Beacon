from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from agent_os.agents.specification import AgentConfig, AgentConfigBundle


class AgentConfigurationLoader:
    """YAML-backed loader for static or hierarchical agent definitions."""

    def load_file(self, path: str | Path) -> AgentConfigBundle:
        return self.loads(Path(path).read_text(encoding="utf-8"))

    def loads(self, content: str) -> AgentConfigBundle:
        data = self._parse_yaml(content)
        agent_entries = data.get("agents", [])

        if not isinstance(agent_entries, Sequence) or isinstance(agent_entries, (str, bytes)):
            raise ValueError("The 'agents' field must be a YAML sequence.")

        configs: list[AgentConfig] = []
        for entry in agent_entries:
            configs.extend(self._parse_agent_entry(entry, parent_agent_id=None))

        metadata = data.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError("The 'metadata' field must be a mapping if provided.")

        return AgentConfigBundle(agents=tuple(configs), metadata=dict(metadata))

    def _parse_yaml(self, content: str) -> Mapping[str, object]:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("PyYAML is required to load agent configuration files.") from exc

        loaded = yaml.safe_load(content) or {}
        if not isinstance(loaded, Mapping):
            raise ValueError("Agent configuration root must be a YAML mapping.")
        return loaded

    def _parse_agent_entry(
        self,
        entry: object,
        *,
        parent_agent_id: str | None,
    ) -> list[AgentConfig]:
        entry_mapping = self._as_mapping(entry, error_message="Each agent entry must be a mapping.")

        agent_id = self._require_string(entry_mapping, "id")
        explicit_parent = entry_mapping.get("parent_agent_id")
        resolved_parent = explicit_parent if isinstance(explicit_parent, str) else parent_agent_id

        children_value = entry_mapping.get("children", [])
        if not isinstance(children_value, Sequence) or isinstance(children_value, (str, bytes)):
            raise ValueError("The 'children' field must be a sequence when provided.")

        child_entries = list(children_value)
        child_ids = tuple(
            self._require_string(
                self._as_mapping(child_entry, error_message="Child agent entry must be a mapping."),
                "id",
            )
            for child_entry in child_entries
        )

        config = AgentConfig(
            agent_id=agent_id,
            role=self._require_string(entry_mapping, "role"),
            name=self._require_string(entry_mapping, "name"),
            model_name=self._require_string(entry_mapping, "model_name"),
            model_adapter_alias=self._require_string(entry_mapping, "model_adapter"),
            memory_namespace=self._require_string(entry_mapping, "memory_namespace"),
            description=self._optional_string(entry_mapping, "description"),
            tool_names=self._string_tuple(entry_mapping.get("tools", []), field_name="tools"),
            parent_agent_id=resolved_parent,
            child_agent_ids=child_ids,
            metadata=self._mapping_value(entry_mapping.get("metadata", {}), field_name="metadata"),
        )

        configs = [config]
        for child_entry in child_entries:
            configs.extend(self._parse_agent_entry(child_entry, parent_agent_id=agent_id))

        return configs

    def _require_string(self, entry: Mapping[str, object], key: str) -> str:
        value = entry.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Agent field '{key}' must be a non-empty string.")
        return value

    def _optional_string(self, entry: Mapping[str, object], key: str) -> str:
        value = entry.get(key, "")
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError(f"Agent field '{key}' must be a string when provided.")
        return value

    def _string_tuple(self, value: object, *, field_name: str) -> tuple[str, ...]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise ValueError(f"Agent field '{field_name}' must be a sequence of strings.")

        result: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(f"Agent field '{field_name}' must only contain strings.")
            result.append(item)
        return tuple(result)

    def _mapping_value(self, value: object, *, field_name: str) -> dict[str, object]:
        if not isinstance(value, Mapping):
            raise ValueError(f"Agent field '{field_name}' must be a mapping.")
        return dict(value)

    def _as_mapping(self, value: object, *, error_message: str) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            raise ValueError(error_message)
        return value
