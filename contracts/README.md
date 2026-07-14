# Shared Contracts

This directory holds language-neutral contracts shared between the Python orchestration core and the TypeScript gateway.

- `runtime-envelope.schema.json` defines the canonical envelope shape for requests, responses, and events crossing process boundaries.

Contract rules:
- envelopes carry explicit semantic payloads
- discussion payloads are expected to remain structured semantic objects
- final-answer candidates remain explicit evaluation objects when they cross runtime boundaries
- embeddings or vector-like payload fragments are supplemental representations only

Concrete transports such as HTTP, stdio, or JSON-RPC should adapt to this contract rather than redefining domain payloads in each runtime.
