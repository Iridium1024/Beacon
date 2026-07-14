# Protocols Module

## Canonical Objects

- `CommunicationMessage` is the canonical semantic object for discussion-round blackboard updates.
- `FinalAnswerCandidate` is the canonical evaluation object for checkpoint, heartbeat, and final-answer review.
- `SharedContext` stores both object families explicitly so the system does not need to infer control state from opaque latent data.

## Representation Layers

- `summary_text` is the primary semantic surface for both users and orchestration control.
- `embedding_vector` is an auxiliary representation attached to a message when semantic compression or similarity support is useful.
- `vector_memory` is an auxiliary retrieval layer attached to shared context.

Auxiliary vector representations may support:
- retrieval
- compression
- clustering
- similarity association
- history trimming

Auxiliary vector representations do not replace:
- checkpoint input
- freeze semantics
- self-check input
- voting input
- dispatcher aggregation input
- report input

## Blackboard Semantics

- broadcast is the primary communication mode
- shared context is the default read/write surface for agents
- discussion messages remain distinct from final-answer candidates
- frozen candidates are the normative input to heartbeat checkpoints
- deprecated point-to-point receiver compatibility remains available only as a compatibility surface

## Protocol Responsibilities

- protocol adapters encode and decode explicit shared-context updates
- protocol adapters do not redefine domain meaning for messages or candidates
- future direct, multicast, and broadcast transport extensions remain possible without changing canonical object semantics
