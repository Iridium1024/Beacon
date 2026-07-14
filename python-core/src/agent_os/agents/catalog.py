from __future__ import annotations

from agent_os.agents.executor_agent import ExecutorAgent
from agent_os.agents.planner_agent import PlannerAgent
from agent_os.agents.registry import AgentRegistry
from agent_os.agents.reviewer_agent import ReviewerAgent


def register_builtin_agents(registry: AgentRegistry) -> AgentRegistry:
    """Register built-in role-based agent types."""

    registry.register_type("planner", PlannerAgent)
    registry.register_type("executor", ExecutorAgent)
    registry.register_type("reviewer", ReviewerAgent)
    return registry


def create_default_agent_registry() -> AgentRegistry:
    """Create a registry seeded with built-in role agents."""

    return register_builtin_agents(AgentRegistry())
