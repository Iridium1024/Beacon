import assert from "node:assert/strict";
import test from "node:test";

import type {
  AgentRuntimeBindingDto,
  CreateAgentRuntimeBindingRequest,
  CreateLocalAgentRequest,
  CreateLocalWorkspaceRequest,
  CreateProviderConnectionRequest,
  LocalWorkspaceCreateResponse,
  ProviderConnectionDto,
} from "../src/application/dto/local-platform-api-contract.js";
import type {
  LocalAgentRuntimePermissionGetResponse,
} from "../src/application/dto/local-platform-operation-response.js";

test("local platform API contract keeps workspace, connection, and binding separate", () => {
  const workspaceRequest = {
    workspaceId: "workspace-1",
    displayName: "Workspace",
    rootPath: "X:/fixture/workspace",
  } satisfies CreateLocalWorkspaceRequest;
  const connectionRequest = {
    connectionId: "connection-1",
    providerKind: "remote_conversation",
    accountAlias: "account-a",
    authMode: "external_connector",
    metadata: { contractOnly: true },
  } satisfies CreateProviderConnectionRequest;
  const bindingRequest = {
    bindingId: "binding-1",
    agentId: "agent-1",
    connectionId: "connection-1",
    runtimeKind: "remote_conversation_instance",
    remoteInstanceId: "instance-1",
    capabilities: ["single-turn-status"],
  } satisfies CreateAgentRuntimeBindingRequest;
  const agentRequest = {
    agentId: "agent-reviewer-1",
    name: "Reviewer",
    description: "Reviews model output.",
    defaultModel: "fake-chat-model",
    capabilities: [
      {
        name: "single-turn-status",
        description: "Runs one local invocation.",
      },
    ],
    toolPermissions: ["workspace.read"],
    runtimeConfig: {
      profile: {
        profileName: "reviewer",
        roleName: "reviewer",
      },
    },
  } satisfies CreateLocalAgentRequest;

  assert.equal(workspaceRequest.workspaceId, "workspace-1");
  assert.equal(agentRequest.runtimeConfig.profile.profileName, "reviewer");
  assert.equal(connectionRequest.connectionId, "connection-1");
  assert.equal(bindingRequest.agentId, "agent-1");
  assert.equal(bindingRequest.connectionId, "connection-1");
});

test("connection and binding DTOs expose status without credential values", () => {
  const connection = {
    connectionId: "connection-1",
    providerKind: "openai_compatible",
    accountAlias: "account-a",
    displayName: "Account A",
    authMode: "managed_credential",
    status: "not_connected",
    metadata: { contractOnly: true },
  } satisfies ProviderConnectionDto;
  const binding = {
    bindingId: "binding-1",
    agentId: "agent-1",
    connectionId: "connection-1",
    runtimeKind: "provider_connection",
    capabilities: ["single-turn-status"],
    status: "not_connected",
    metadata: { contractOnly: true },
  } satisfies AgentRuntimeBindingDto;

  assert.deepEqual(Object.keys(connection).sort(), [
    "accountAlias",
    "authMode",
    "connectionId",
    "displayName",
    "metadata",
    "providerKind",
    "status",
  ]);
  assert.deepEqual(Object.keys(binding).sort(), [
    "agentId",
    "bindingId",
    "capabilities",
    "connectionId",
    "metadata",
    "runtimeKind",
    "status",
  ]);
});

test("runtime permission DTO exposes read-only audit flags", () => {
  const response = {
    runtimePermission: {
      workspaceId: "workspace-1",
      agentId: "agent-1",
      profileName: "Agent",
      roleName: "Agent",
      runtimeKind: "provider_backed_model",
      providerBackedModel: true,
      runtimeConnected: false,
      readModelOnly: true,
      configuredProfile: {
        delegated_context_delivery: "none",
        file_permission: "file_ref_metadata_only",
      },
      capabilities: {
        denied: [
          "real_runtime_connection",
          "credential_store",
          "websocket_transport",
          "file_body_read",
          "provider_prompt_injection",
        ],
      },
      grant: {
        revoked: false,
        real_runtime_connected: false,
        credential_store_connected: false,
      },
      deliveryPlan: {
        materialized_text_included: false,
        file_bodies_included: false,
        real_runtime_connected: false,
        provider_prompt_injected: false,
      },
      boundary: {
        read_model_only: true,
        invocation_created: false,
        model_provider_invoked: false,
      },
    },
  } satisfies LocalAgentRuntimePermissionGetResponse;

  assert.equal(response.runtimePermission.readModelOnly, true);
  assert.equal(response.runtimePermission.runtimeConnected, false);
  assert.equal(
    response.runtimePermission.deliveryPlan.materialized_text_included,
    false,
  );
  assert.doesNotMatch(
    JSON.stringify(response),
    /apiKey|Authorization|Cookie|credentialValue/i,
  );
});

test("workspace create response preserves invocation-ready overview shape", () => {
  const response = {
    created: true,
    workspaceSourceEventSequence: 1,
    workspace: {
      workspace: {
        workspaceId: "workspace-1",
        sourceEventSequence: 1,
        displayName: "Workspace",
        rootPath: "X:/fixture/workspace",
        status: "active",
        createdAt: "2026-06-05T00:00:00+00:00",
        updatedAt: "2026-06-05T00:00:00+00:00",
        workspaceState: {},
        bindingState: {},
        metadata: {},
      },
      context: null,
      agents: [],
      tasks: [],
      issues: [],
    },
    baseline: {
      workspaceId: "workspace-1",
      contextCreated: true,
      agentCreated: true,
      context: null,
      agents: [],
    },
  } satisfies LocalWorkspaceCreateResponse;

  assert.equal(response.workspace.workspace.workspaceId, "workspace-1");
  assert.equal(response.baseline.workspaceId, "workspace-1");
  assert.equal(response.created, true);
});
