from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from agent_os.agents.base_agent import BaseAgent
from agent_os.agents.specification import AgentConfig, AgentConfigBundle, AgentDependencies, AgentFactory


DependencyResolver = Callable[[AgentConfig], AgentDependencies]


class AgentRegistry:
    """Registry for agent factories, created agents, and parent-child lookups."""

    def __init__(self) -> None:
        self._factories: dict[str, AgentFactory] = {}
        self._agents: dict[str, BaseAgent] = {}

    def register_factory(self, role: str, factory: AgentFactory) -> None:
        self._factories[role] = factory

    def register_type(self, role: str, agent_type: type[BaseAgent]) -> None:
        def factory(config: AgentConfig, dependencies: AgentDependencies) -> BaseAgent:
            return agent_type(
                config=config,
                memory=dependencies.memory,
                tools=dependencies.tools,
                model_access=dependencies.model_access,
            )

        self.register_factory(role, factory)

    def create(self, config: AgentConfig, dependencies: AgentDependencies) -> BaseAgent:
        try:
            factory = self._factories[config.role]
        except KeyError as exc:
            raise KeyError(f"No factory registered for agent role '{config.role}'.") from exc

        agent = factory(config, dependencies)
        self._agents[agent.agent_id] = agent
        return agent

    def create_many(
        self,
        bundle: AgentConfigBundle,
        dependency_resolver: DependencyResolver,
    ) -> tuple[BaseAgent, ...]:
        return tuple(
            self.create(config, dependency_resolver(config))
            for config in bundle.agents
        )

    def add(self, agent: BaseAgent) -> None:
        self._agents[agent.agent_id] = agent

    def get(self, agent_id: str) -> BaseAgent | None:
        return self._agents.get(agent_id)

    def list(self) -> tuple[BaseAgent, ...]:
        return tuple(self._agents.values())

    def get_children(self, agent_id: str) -> tuple[BaseAgent, ...]:
        return tuple(
            agent
            for agent in self._agents.values()
            if agent.parent_agent_id == agent_id
        )

    def hierarchy(self) -> Mapping[str | None, tuple[BaseAgent, ...]]:
        nodes: dict[str | None, list[BaseAgent]] = {}
        for agent in self._agents.values():
            nodes.setdefault(agent.parent_agent_id, []).append(agent)

        return {
            parent_agent_id: tuple(children)
            for parent_agent_id, children in nodes.items()
        }
