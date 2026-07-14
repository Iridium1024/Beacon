import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

interface HeartbeatTerminalSharedManifest {
  schema_id: string;
  envelope: {
    kind: string;
    protocol_version: string;
    body_location: string;
  };
  payload: {
    required_fields: string[];
    candidate: {
      required_fields: string[];
    };
    section_vocabulary: string[];
    display_metadata: {
      required_keys: string[];
      display_policy_version_key: string;
      display_section_order_key: string;
      display_omit_empty_sections_key: string;
      display_omit_empty_sections_value: boolean;
      display_section_count_key: string;
      retained_item_count_key: string;
      omission_rules: {
        metadata_key: string;
        non_omittable_sections: string[];
      };
      truncation_rules: Record<
        string,
        {
          count_key: string;
          collection_field: string;
          limit_key: string;
          section_kind: string;
        }
      >;
    };
  };
}

const resolveHeartbeatTerminalSharedManifestPath = (): string => {
  const currentDir = dirname(fileURLToPath(import.meta.url));
  const candidatePaths = [
    "../../../../contracts/heartbeat-terminal-export.manifest.json",
    "../../../../../contracts/heartbeat-terminal-export.manifest.json",
    "../../../../../../../contracts/heartbeat-terminal-export.manifest.json",
  ].map((relativePath) => resolve(currentDir, relativePath));
  const manifestPath = candidatePaths.find((candidatePath) =>
    existsSync(candidatePath),
  );
  if (!manifestPath) {
    throw new Error("Heartbeat terminal shared manifest was not found.");
  }
  return manifestPath;
};

const HEARTBEAT_TERMINAL_SHARED_MANIFEST_PATH =
  resolveHeartbeatTerminalSharedManifestPath();

const loadHeartbeatTerminalSharedManifest = (): HeartbeatTerminalSharedManifest =>
  JSON.parse(
    readFileSync(HEARTBEAT_TERMINAL_SHARED_MANIFEST_PATH, "utf-8"),
  ) as HeartbeatTerminalSharedManifest;

const HEARTBEAT_TERMINAL_SHARED_MANIFEST = loadHeartbeatTerminalSharedManifest();
const HEARTBEAT_TERMINAL_PAYLOAD_MANIFEST = HEARTBEAT_TERMINAL_SHARED_MANIFEST.payload;
const HEARTBEAT_TERMINAL_DISPLAY_METADATA_MANIFEST =
  HEARTBEAT_TERMINAL_PAYLOAD_MANIFEST.display_metadata;
const HEARTBEAT_TERMINAL_OMISSION_RULES =
  HEARTBEAT_TERMINAL_DISPLAY_METADATA_MANIFEST.omission_rules;
const HEARTBEAT_TERMINAL_TRUNCATION_RULES =
  HEARTBEAT_TERMINAL_DISPLAY_METADATA_MANIFEST.truncation_rules;

const HEARTBEAT_TERMINAL_EXPORT_REQUIRED_FIELDS = [
  ...HEARTBEAT_TERMINAL_PAYLOAD_MANIFEST.required_fields,
] as const;
const HEARTBEAT_TERMINAL_EXPORT_CANDIDATE_REQUIRED_FIELDS = [
  ...HEARTBEAT_TERMINAL_PAYLOAD_MANIFEST.candidate.required_fields,
] as const;
const HEARTBEAT_TERMINAL_EXPORT_DISPLAY_METADATA_REQUIRED_FIELDS = [
  ...HEARTBEAT_TERMINAL_DISPLAY_METADATA_MANIFEST.required_keys,
] as const;

export const HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID =
  HEARTBEAT_TERMINAL_SHARED_MANIFEST.schema_id;
export const HEARTBEAT_TERMINAL_PROTOCOL_KIND =
  HEARTBEAT_TERMINAL_SHARED_MANIFEST.envelope.kind;
export const HEARTBEAT_TERMINAL_PROTOCOL_VERSION =
  HEARTBEAT_TERMINAL_SHARED_MANIFEST.envelope.protocol_version;
export const HEARTBEAT_TERMINAL_ENVELOPE_BODY_FIELD =
  HEARTBEAT_TERMINAL_SHARED_MANIFEST.envelope.body_location;
export const HEARTBEAT_TERMINAL_EXPORT_SECTION_KIND_VOCABULARY = [
  ...HEARTBEAT_TERMINAL_PAYLOAD_MANIFEST.section_vocabulary,
] as const;

type UnknownRecord = Record<string, unknown>;
type SectionKind = (typeof HEARTBEAT_TERMINAL_EXPORT_SECTION_KIND_VOCABULARY)[number];

export interface ProtocolEnvelope<TPayload = UnknownRecord> {
  protocol_version: string;
  request_id: string;
  kind: string;
  payload: TPayload;
  metadata?: Record<string, string>;
}

export interface HeartbeatTerminalExportCandidate {
  candidate_id: string;
  checkpoint_id: string;
  summary: string;
  source_round: number | null;
  supporting_context_refs: string[];
  final_decision: string;
  semantic_state: string;
  reservation_level: string;
  consumer_readiness: string;
  retained_issue_preview: string | null;
  next_step_preview: string | null;
}

export interface HeartbeatTerminalExportRetainedItem {
  category: string;
  severity: string | null;
  blocker: boolean;
  priority_rank: number;
  supporting_roles: string[];
  summary: string | null;
  impact_on_decision: string | null;
}

export interface HeartbeatTerminalDisplaySection {
  kind: SectionKind;
  title: string;
  lines: string[];
}

export interface HeartbeatTerminalDisplayMetadata extends UnknownRecord {
  display_policy_version: string;
  display_section_order: SectionKind[];
  display_omit_empty_sections: true;
  display_retained_items_limit: number;
  display_decision_rationale_limit: number;
  display_recommended_next_actions_limit: number;
  display_section_count: number;
  retained_item_count: number;
  display_retained_items_count: number;
  display_retained_items_truncated: boolean;
  display_decision_rationale_count: number;
  display_decision_rationale_truncated: boolean;
  display_recommended_next_actions_count: number;
  display_recommended_next_actions_truncated: boolean;
  display_omitted_sections: SectionKind[];
}

export interface HeartbeatTerminalExportPayload {
  schema_id: typeof HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID;
  final_decision: string;
  consumer_readiness: string;
  candidate: HeartbeatTerminalExportCandidate;
  decision_rationale: string[];
  recommended_next_actions: string[];
  top_retained_items: HeartbeatTerminalExportRetainedItem[];
  reservation_summary: string | null;
  display_sections: HeartbeatTerminalDisplaySection[];
  display_metadata: HeartbeatTerminalDisplayMetadata;
}

export interface HeartbeatTerminalProtocolEnvelope
  extends ProtocolEnvelope<HeartbeatTerminalExportPayload> {}

export const parseHeartbeatTerminalProtocolEnvelope = (
  value: unknown,
): HeartbeatTerminalProtocolEnvelope => {
  const envelope = expectRecord(value, "ProtocolEnvelope");
  const protocolVersion = expectNonEmptyString(
    envelope.protocol_version,
    "ProtocolEnvelope.protocol_version",
  );
  if (protocolVersion !== HEARTBEAT_TERMINAL_PROTOCOL_VERSION) {
    throw new Error(
      `Heartbeat terminal ProtocolEnvelope.protocol_version must equal ${HEARTBEAT_TERMINAL_PROTOCOL_VERSION}.`,
    );
  }
  const requestId = expectNonEmptyString(
    envelope.request_id,
    "ProtocolEnvelope.request_id",
  );
  const kind = expectNonEmptyString(envelope.kind, "ProtocolEnvelope.kind");
  if (kind !== HEARTBEAT_TERMINAL_PROTOCOL_KIND) {
    throw new Error(
      `Heartbeat terminal ProtocolEnvelope.kind must equal ${HEARTBEAT_TERMINAL_PROTOCOL_KIND}.`,
    );
  }
  const payload = parseHeartbeatTerminalExportPayload(
    expectRecord(
      envelope[HEARTBEAT_TERMINAL_ENVELOPE_BODY_FIELD],
      "ProtocolEnvelope.payload",
    ),
  );
  const metadata = parseStringRecord(
    envelope.metadata,
    "ProtocolEnvelope.metadata",
  );
  return {
    protocol_version: protocolVersion,
    request_id: requestId,
    kind,
    payload,
    metadata,
  };
};

export const decodeHeartbeatTerminalExport = (
  value: unknown,
): HeartbeatTerminalExportPayload => parseHeartbeatTerminalProtocolEnvelope(value).payload;

export const parseHeartbeatTerminalExportPayload = (
  value: unknown,
): HeartbeatTerminalExportPayload => {
  const payload = expectRecord(value, "HeartbeatTerminalExportPayload");
  assertRequiredFields(
    payload,
    HEARTBEAT_TERMINAL_EXPORT_REQUIRED_FIELDS,
    "HeartbeatTerminalExportPayload",
  );
  const schemaId = expectNonEmptyString(
    payload.schema_id,
    "HeartbeatTerminalExportPayload.schema_id",
  );
  if (schemaId !== HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID) {
    throw new Error(
      `Heartbeat terminal payload schema_id must equal ${HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID}.`,
    );
  }
  const finalDecision = expectNonEmptyString(
    payload.final_decision,
    "HeartbeatTerminalExportPayload.final_decision",
  );
  const consumerReadiness = expectNonEmptyString(
    payload.consumer_readiness,
    "HeartbeatTerminalExportPayload.consumer_readiness",
  );
  const candidate = parseHeartbeatTerminalExportCandidate(payload.candidate);
  if (candidate.final_decision !== finalDecision) {
    throw new Error(
      "Heartbeat terminal payload final_decision must match candidate.final_decision.",
    );
  }
  if (candidate.consumer_readiness !== consumerReadiness) {
    throw new Error(
      "Heartbeat terminal payload consumer_readiness must match candidate.consumer_readiness.",
    );
  }
  const decisionRationale = expectStringArray(
    payload.decision_rationale,
    "HeartbeatTerminalExportPayload.decision_rationale",
  );
  const recommendedNextActions = expectStringArray(
    payload.recommended_next_actions,
    "HeartbeatTerminalExportPayload.recommended_next_actions",
  );
  const topRetainedItems = expectArray(
    payload.top_retained_items,
    "HeartbeatTerminalExportPayload.top_retained_items",
  ).map((item, index) =>
    parseHeartbeatTerminalRetainedItem(
      item,
      `HeartbeatTerminalExportPayload.top_retained_items[${index}]`,
    ),
  );
  const reservationSummary = expectOptionalString(
    payload.reservation_summary,
    "HeartbeatTerminalExportPayload.reservation_summary",
  );
  const displaySections = expectArray(
    payload.display_sections,
    "HeartbeatTerminalExportPayload.display_sections",
  ).map((section, index) =>
    parseHeartbeatTerminalDisplaySection(
      section,
      `HeartbeatTerminalExportPayload.display_sections[${index}]`,
    ),
  );
  if (displaySections.length === 0) {
    throw new Error(
      "Heartbeat terminal payload display_sections must contain at least one section.",
    );
  }
  assertUniqueSectionKinds(displaySections);
  const displayMetadata = parseHeartbeatTerminalDisplayMetadata(
    payload.display_metadata,
  );
  assertDisplayContract({
    decisionRationale,
    recommendedNextActions,
    topRetainedItems,
    displaySections,
    displayMetadata,
  });
  return {
    schema_id: HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID,
    final_decision: finalDecision,
    consumer_readiness: consumerReadiness,
    candidate,
    decision_rationale: decisionRationale,
    recommended_next_actions: recommendedNextActions,
    top_retained_items: topRetainedItems,
    reservation_summary: reservationSummary,
    display_sections: displaySections,
    display_metadata: displayMetadata,
  };
};

const parseHeartbeatTerminalExportCandidate = (
  value: unknown,
): HeartbeatTerminalExportCandidate => {
  const candidate = expectRecord(value, "HeartbeatTerminalExportCandidate");
  assertRequiredFields(
    candidate,
    HEARTBEAT_TERMINAL_EXPORT_CANDIDATE_REQUIRED_FIELDS,
    "HeartbeatTerminalExportCandidate",
  );
  return {
    candidate_id: expectNonEmptyString(
      candidate.candidate_id,
      "HeartbeatTerminalExportCandidate.candidate_id",
    ),
    checkpoint_id: expectNonEmptyString(
      candidate.checkpoint_id,
      "HeartbeatTerminalExportCandidate.checkpoint_id",
    ),
    summary: expectNonEmptyString(
      candidate.summary,
      "HeartbeatTerminalExportCandidate.summary",
    ),
    source_round: expectOptionalInteger(
      candidate.source_round,
      "HeartbeatTerminalExportCandidate.source_round",
    ),
    supporting_context_refs: expectStringArray(
      candidate.supporting_context_refs,
      "HeartbeatTerminalExportCandidate.supporting_context_refs",
    ),
    final_decision: expectNonEmptyString(
      candidate.final_decision,
      "HeartbeatTerminalExportCandidate.final_decision",
    ),
    semantic_state: expectNonEmptyString(
      candidate.semantic_state,
      "HeartbeatTerminalExportCandidate.semantic_state",
    ),
    reservation_level: expectNonEmptyString(
      candidate.reservation_level,
      "HeartbeatTerminalExportCandidate.reservation_level",
    ),
    consumer_readiness: expectNonEmptyString(
      candidate.consumer_readiness,
      "HeartbeatTerminalExportCandidate.consumer_readiness",
    ),
    retained_issue_preview: expectOptionalString(
      candidate.retained_issue_preview,
      "HeartbeatTerminalExportCandidate.retained_issue_preview",
    ),
    next_step_preview: expectOptionalString(
      candidate.next_step_preview,
      "HeartbeatTerminalExportCandidate.next_step_preview",
    ),
  };
};

const parseHeartbeatTerminalRetainedItem = (
  value: unknown,
  label: string,
): HeartbeatTerminalExportRetainedItem => {
  const item = expectRecord(value, label);
  return {
    category: expectNonEmptyString(item.category, `${label}.category`),
    severity: expectOptionalString(item.severity, `${label}.severity`),
    blocker: expectBoolean(item.blocker, `${label}.blocker`),
    priority_rank: expectInteger(item.priority_rank, `${label}.priority_rank`),
    supporting_roles: expectStringArray(
      item.supporting_roles ?? [],
      `${label}.supporting_roles`,
    ),
    summary: expectOptionalString(item.summary, `${label}.summary`),
    impact_on_decision: expectOptionalString(
      item.impact_on_decision,
      `${label}.impact_on_decision`,
    ),
  };
};

const parseHeartbeatTerminalDisplaySection = (
  value: unknown,
  label: string,
): HeartbeatTerminalDisplaySection => {
  const section = expectRecord(value, label);
  const kind = expectSectionKind(section.kind, `${label}.kind`);
  const title = expectNonEmptyString(section.title, `${label}.title`);
  const lines = expectStringArray(section.lines, `${label}.lines`);
  if (lines.length === 0) {
    throw new Error(`${label}.lines must not be empty.`);
  }
  return {
    kind,
    title,
    lines,
  };
};

const parseHeartbeatTerminalDisplayMetadata = (
  value: unknown,
): HeartbeatTerminalDisplayMetadata => {
  const metadata = expectRecord(value, "HeartbeatTerminalDisplayMetadata");
  assertRequiredFields(
    metadata,
    HEARTBEAT_TERMINAL_EXPORT_DISPLAY_METADATA_REQUIRED_FIELDS,
    "HeartbeatTerminalDisplayMetadata",
  );
  const displayPolicyVersion = expectNonEmptyString(
    metadata[HEARTBEAT_TERMINAL_DISPLAY_METADATA_MANIFEST.display_policy_version_key],
    `HeartbeatTerminalDisplayMetadata.${HEARTBEAT_TERMINAL_DISPLAY_METADATA_MANIFEST.display_policy_version_key}`,
  );
  const displaySectionOrder = expectSectionKindArray(
    metadata[HEARTBEAT_TERMINAL_DISPLAY_METADATA_MANIFEST.display_section_order_key],
    `HeartbeatTerminalDisplayMetadata.${HEARTBEAT_TERMINAL_DISPLAY_METADATA_MANIFEST.display_section_order_key}`,
  );
  assertCompleteSectionVocabulary(displaySectionOrder);
  const displayOmittedSections = expectSectionKindArray(
    metadata[HEARTBEAT_TERMINAL_OMISSION_RULES.metadata_key],
    `HeartbeatTerminalDisplayMetadata.${HEARTBEAT_TERMINAL_OMISSION_RULES.metadata_key}`,
  );
  if (
    HEARTBEAT_TERMINAL_OMISSION_RULES.non_omittable_sections.some((sectionKind) =>
      displayOmittedSections.includes(sectionKind as SectionKind),
    )
  ) {
    throw new Error(
      "Heartbeat terminal display_omitted_sections must not omit required sections.",
    );
  }
  return {
    ...metadata,
    display_policy_version: displayPolicyVersion,
    display_section_order: displaySectionOrder,
    display_omit_empty_sections: expectTrue(
      metadata[HEARTBEAT_TERMINAL_DISPLAY_METADATA_MANIFEST.display_omit_empty_sections_key],
      `HeartbeatTerminalDisplayMetadata.${HEARTBEAT_TERMINAL_DISPLAY_METADATA_MANIFEST.display_omit_empty_sections_key}`,
    ),
    display_retained_items_limit: expectPositiveInteger(
      metadata.display_retained_items_limit,
      "HeartbeatTerminalDisplayMetadata.display_retained_items_limit",
    ),
    display_decision_rationale_limit: expectPositiveInteger(
      metadata.display_decision_rationale_limit,
      "HeartbeatTerminalDisplayMetadata.display_decision_rationale_limit",
    ),
    display_recommended_next_actions_limit: expectPositiveInteger(
      metadata.display_recommended_next_actions_limit,
      "HeartbeatTerminalDisplayMetadata.display_recommended_next_actions_limit",
    ),
    display_section_count: expectInteger(
      metadata.display_section_count,
      "HeartbeatTerminalDisplayMetadata.display_section_count",
    ),
    retained_item_count: expectInteger(
      metadata.retained_item_count,
      "HeartbeatTerminalDisplayMetadata.retained_item_count",
    ),
    display_retained_items_count: expectInteger(
      metadata.display_retained_items_count,
      "HeartbeatTerminalDisplayMetadata.display_retained_items_count",
    ),
    display_retained_items_truncated: expectBoolean(
      metadata.display_retained_items_truncated,
      "HeartbeatTerminalDisplayMetadata.display_retained_items_truncated",
    ),
    display_decision_rationale_count: expectInteger(
      metadata.display_decision_rationale_count,
      "HeartbeatTerminalDisplayMetadata.display_decision_rationale_count",
    ),
    display_decision_rationale_truncated: expectBoolean(
      metadata.display_decision_rationale_truncated,
      "HeartbeatTerminalDisplayMetadata.display_decision_rationale_truncated",
    ),
    display_recommended_next_actions_count: expectInteger(
      metadata.display_recommended_next_actions_count,
      "HeartbeatTerminalDisplayMetadata.display_recommended_next_actions_count",
    ),
    display_recommended_next_actions_truncated: expectBoolean(
      metadata.display_recommended_next_actions_truncated,
      "HeartbeatTerminalDisplayMetadata.display_recommended_next_actions_truncated",
    ),
    display_omitted_sections: displayOmittedSections,
  };
};

const assertDisplayContract = ({
  decisionRationale,
  recommendedNextActions,
  topRetainedItems,
  displaySections,
  displayMetadata,
}: {
  decisionRationale: string[];
  recommendedNextActions: string[];
  topRetainedItems: HeartbeatTerminalExportRetainedItem[];
  displaySections: HeartbeatTerminalDisplaySection[];
  displayMetadata: HeartbeatTerminalDisplayMetadata;
}): void => {
  const actualSectionKinds = displaySections.map((section) => section.kind);
  const expectedOmittedSections = HEARTBEAT_TERMINAL_EXPORT_SECTION_KIND_VOCABULARY.filter(
    (kind) => !actualSectionKinds.includes(kind),
  );
  if (
    displayMetadata.display_omitted_sections.join("|") !==
    expectedOmittedSections.join("|")
  ) {
    throw new Error(
      "Heartbeat terminal display_omitted_sections must match the actual omitted sections.",
    );
  }
  const expectedRenderedOrder = displayMetadata.display_section_order.filter(
    (kind) => !displayMetadata.display_omitted_sections.includes(kind),
  );
  if (actualSectionKinds.join("|") !== expectedRenderedOrder.join("|")) {
    throw new Error(
      "Heartbeat terminal display_sections must preserve display_section_order after omission.",
    );
  }
  if (
    displayMetadata[
      HEARTBEAT_TERMINAL_DISPLAY_METADATA_MANIFEST
        .display_section_count_key as keyof HeartbeatTerminalDisplayMetadata
    ] !== displaySections.length
  ) {
    throw new Error(
      "Heartbeat terminal display_section_count must match display_sections.length.",
    );
  }
  if (
    displayMetadata[
      HEARTBEAT_TERMINAL_DISPLAY_METADATA_MANIFEST
        .retained_item_count_key as keyof HeartbeatTerminalDisplayMetadata
    ] !== topRetainedItems.length
  ) {
    throw new Error(
      "Heartbeat terminal retained_item_count must match top_retained_items.length.",
    );
  }
  const collectionValues: Record<string, unknown[]> = {
    top_retained_items: topRetainedItems,
    decision_rationale: decisionRationale,
    recommended_next_actions: recommendedNextActions,
  };
  for (const [truncationKey, truncationRule] of Object.entries(
    HEARTBEAT_TERMINAL_TRUNCATION_RULES,
  )) {
    const countKey = truncationRule.count_key as keyof HeartbeatTerminalDisplayMetadata;
    const limitKey = truncationRule.limit_key as keyof HeartbeatTerminalDisplayMetadata;
    if (
      displayMetadata[countKey] !==
      getSectionLineCount(displaySections, truncationRule.section_kind as SectionKind)
    ) {
      throw new Error(
        `Heartbeat terminal ${String(countKey)} must match the section preview length.`,
      );
    }
    const collectionValue = collectionValues[truncationRule.collection_field] ?? [];
    const previewLimit = displayMetadata[limitKey];
    if (
      typeof previewLimit !== "number" ||
      displayMetadata[truncationKey as keyof HeartbeatTerminalDisplayMetadata] !==
        collectionValue.length > previewLimit
    ) {
      throw new Error(
        `Heartbeat terminal ${truncationKey} must match preview budgeting.`,
      );
    }
  }
};

const assertRequiredFields = (
  value: UnknownRecord,
  fields: readonly string[],
  label: string,
): void => {
  const missingFields = fields.filter((field) => !(field in value));
  if (missingFields.length > 0) {
    throw new Error(`${label} is missing required fields: ${missingFields.join(", ")}.`);
  }
};

const assertUniqueSectionKinds = (
  sections: HeartbeatTerminalDisplaySection[],
): void => {
  const sectionKinds = sections.map((section) => section.kind);
  if (new Set(sectionKinds).size !== sectionKinds.length) {
    throw new Error(
      "Heartbeat terminal display_sections must not repeat section kinds.",
    );
  }
};

const assertCompleteSectionVocabulary = (sectionKinds: SectionKind[]): void => {
  if (
    new Set(sectionKinds).size !== HEARTBEAT_TERMINAL_EXPORT_SECTION_KIND_VOCABULARY.length
  ) {
    throw new Error(
      "Heartbeat terminal display_section_order must cover each section kind exactly once.",
    );
  }
  const expectedKinds = [...HEARTBEAT_TERMINAL_EXPORT_SECTION_KIND_VOCABULARY].sort();
  const actualKinds = [...sectionKinds].sort();
  if (expectedKinds.join("|") !== actualKinds.join("|")) {
    throw new Error(
      "Heartbeat terminal display_section_order must match the section vocabulary.",
    );
  }
};

const parseStringRecord = (
  value: unknown,
  label: string,
): Record<string, string> | undefined => {
  if (value === undefined) {
    return undefined;
  }
  const record = expectRecord(value, label);
  const parsedRecord: Record<string, string> = {};
  for (const [key, nestedValue] of Object.entries(record)) {
    parsedRecord[expectNonEmptyString(key, `${label} key`)] = expectString(
      nestedValue,
      `${label}.${key}`,
    );
  }
  return parsedRecord;
};

const expectRecord = (value: unknown, label: string): UnknownRecord => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be an object.`);
  }
  return value as UnknownRecord;
};

const expectArray = (value: unknown, label: string): unknown[] => {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array.`);
  }
  return value;
};

const expectString = (value: unknown, label: string): string => {
  if (typeof value !== "string") {
    throw new Error(`${label} must be a string.`);
  }
  return value;
};

const expectNonEmptyString = (value: unknown, label: string): string => {
  const normalizedValue = expectString(value, label).trim();
  if (!normalizedValue) {
    throw new Error(`${label} must be non-empty.`);
  }
  return normalizedValue;
};

const expectOptionalString = (value: unknown, label: string): string | null => {
  if (value === null || value === undefined) {
    return null;
  }
  return expectNonEmptyString(value, label);
};

const expectStringArray = (value: unknown, label: string): string[] =>
  expectArray(value, label).map((entry, index) =>
    expectNonEmptyString(entry, `${label}[${index}]`),
  );

const expectBoolean = (value: unknown, label: string): boolean => {
  if (typeof value !== "boolean") {
    throw new Error(`${label} must be a boolean.`);
  }
  return value;
};

const expectTrue = (value: unknown, label: string): true => {
  if (value !== true) {
    throw new Error(`${label} must equal true.`);
  }
  return true;
};

const expectInteger = (value: unknown, label: string): number => {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`${label} must be an integer.`);
  }
  return value;
};

const expectOptionalInteger = (value: unknown, label: string): number | null => {
  if (value === null || value === undefined) {
    return null;
  }
  return expectInteger(value, label);
};

const expectPositiveInteger = (value: unknown, label: string): number => {
  const parsedValue = expectInteger(value, label);
  if (parsedValue <= 0) {
    throw new Error(`${label} must be a positive integer.`);
  }
  return parsedValue;
};

const expectSectionKind = (value: unknown, label: string): SectionKind => {
  const parsedValue = expectNonEmptyString(value, label);
  if (
    !HEARTBEAT_TERMINAL_EXPORT_SECTION_KIND_VOCABULARY.includes(
      parsedValue as SectionKind,
    )
  ) {
    throw new Error(`${label} must use the heartbeat terminal section vocabulary.`);
  }
  return parsedValue as SectionKind;
};

const expectSectionKindArray = (value: unknown, label: string): SectionKind[] =>
  expectArray(value, label).map((entry, index) =>
    expectSectionKind(entry, `${label}[${index}]`),
  );

const getSectionLineCount = (
  sections: HeartbeatTerminalDisplaySection[],
  kind: SectionKind,
): number => {
  const section = sections.find((candidateSection) => candidateSection.kind === kind);
  return section?.lines.length ?? 0;
};
