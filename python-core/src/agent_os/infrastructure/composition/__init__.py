"""Infrastructure composition helpers for platform runtime slices."""

__all__ = (
    "SqliteLocalSingleTurnPlatformUseCaseComponents",
    "SqliteSingleTurnPlatformRuntimeComponents",
    "build_sqlite_local_single_turn_platform_use_case",
    "build_sqlite_single_turn_platform_runtime",
)


def __getattr__(name: str):
    if name in {
        "SqliteLocalSingleTurnPlatformUseCaseComponents",
        "build_sqlite_local_single_turn_platform_use_case",
    }:
        from agent_os.infrastructure.composition.local_single_turn_use_case import (
            SqliteLocalSingleTurnPlatformUseCaseComponents,
            build_sqlite_local_single_turn_platform_use_case,
        )

        values = {
            "SqliteLocalSingleTurnPlatformUseCaseComponents": (
                SqliteLocalSingleTurnPlatformUseCaseComponents
            ),
            "build_sqlite_local_single_turn_platform_use_case": (
                build_sqlite_local_single_turn_platform_use_case
            ),
        }
        return values[name]
    if name in {
        "SqliteSingleTurnPlatformRuntimeComponents",
        "build_sqlite_single_turn_platform_runtime",
    }:
        from agent_os.infrastructure.composition.single_turn_runtime import (
            SqliteSingleTurnPlatformRuntimeComponents,
            build_sqlite_single_turn_platform_runtime,
        )

        values = {
            "SqliteSingleTurnPlatformRuntimeComponents": (
                SqliteSingleTurnPlatformRuntimeComponents
            ),
            "build_sqlite_single_turn_platform_runtime": (
                build_sqlite_single_turn_platform_runtime
            ),
        }
        return values[name]
    raise AttributeError(name)
