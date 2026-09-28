export type RiskLevel = "black" | "red" | "yellow" | "green";
export type AlertKind = "fire";
export type RequestStatus = "new" | "in_progress" | "completed" | "rejected";
export type SmsDeliveryStatus = "delivered" | "failed";
export type SmsProcessingStatus = "undelivered" | "new" | "in_progress" | "completed" | "cancelled";
export type UserRole = "technician" | "district_dispatcher" | "ods_dispatcher" | "response_team";
export type ExecutorGroup = "technician" | "response_team";
export type RequestPriority = "normal" | "high" | "emergency";
export type RequestKind = "inspection" | "repair" | "emergency";
export type ExecutorRequestAction = "comment" | "release" | "complete" | "cancel";

export interface RequestComment {
  id: string;
  employeeId: string;
  employeeName: string;
  text: string;
  createdAt: string;
}

export interface Employee {
  id: string;
  name: string;
  group: ExecutorGroup;
  districts: string[];
  objectIds: string[];
}

export interface CreateRequestInput {
  alertId: string;
  requestKind: RequestKind;
  executorGroup: ExecutorGroup;
  priority: RequestPriority;
  description: string;
  dueAt?: string;
  comment?: string;
  creatorRole: Extract<UserRole, "district_dispatcher" | "ods_dispatcher">;
}

export interface Channel {
  id: string;
  name: string;
  sensorType: string;
  picketRaw?: string | null;
  picketSortKey?: number | null;
  value?: string;
  state?: "normal" | "warning" | "danger" | "malfunction";
  deviceAgeYears?: number | null;
  ageSource?: "first_seen" | "generated_demo" | "imported";
  maintenanceNote?: string;
  metadataSource?: string;
}

export interface RiskObject {
  id: string;
  name: string;
  district: string;
  channelCount: number;
  level: RiskLevel;
  probability: number;
  channels: Channel[];
}

export interface RiskFactor { label: string; contribution: number; detail: string }
export interface LevelHistory { fromLevel?: RiskLevel; toLevel: RiskLevel; changedAt: string }
export interface Decision { decision: string; comment?: string; decidedAt: string }

export interface Alert {
  id: string;
  episodeId: string;
  objectId: string;
  objectName: string;
  kind: AlertKind;
  level: RiskLevel;
  horizon: string;
  probability: number;
  pNow: number;
  p6h: number;
  p12h: number;
  p24h: number;
  calculatedAt: string;
  modelVersion: string;
  stale: boolean;
  current: boolean;
  isDemo?: boolean;
  picketFrom?: number;
  picketTo?: number;
  channels: Channel[];
  factors: RiskFactor[];
  recommendation: string;
  context: string;
  recipients: string[];
  history: LevelHistory[];
  decisions: Decision[];
}

export interface ModelDemoSensor {
  id: string;
  name: string;
  sensorType: string;
  picket?: string | null;
  value: string;
  state: string;
}

export interface ModelDemoInput {
  label: string;
  value: string;
}

export interface ModelDemoScenario {
  id: string;
  sourceTimestamp: string;
  objectId: string;
  objectName: string;
  district: string;
  dangerousSection: string;
  sensors: ModelDemoSensor[];
  inputs: ModelDemoInput[];
}

export interface ModelDemoFactor {
  horizon: string;
  feature: string;
  value: number;
  contribution: number;
}

export interface ModelDemoPrediction {
  calculatedAt: string;
  pNow: number;
  p6h: number;
  p12h: number;
  p24h: number;
  decisions: Record<string, boolean>;
  factors: ModelDemoFactor[];
}

export interface ModelDemoCalculation {
  calculationId: string;
  scenario: ModelDemoScenario;
  prediction: ModelDemoPrediction;
}

export interface MaintenanceRequest {
  id: string;
  publicId: string;
  alertId: string;
  objectId: string;
  objectName: string;
  picket?: string;
  recommendation: string;
  requestKind: RequestKind;
  executorGroup: ExecutorGroup;
  priority: RequestPriority;
  description: string;
  dueAt?: string;
  comment?: string;
  creatorRole: string;
  assigneeId?: string;
  assigneeName?: string;
  comments: RequestComment[];
  status: RequestStatus;
  createdAt: string;
  updatedAt: string;
}

export interface SmsNotification {
  id: string;
  episodeId: string;
  episodeTitle: string;
  alertLevel: RiskLevel;
  recipientId: string;
  role: string;
  recipientName: string;
  sentAt: string;
  content: string;
  incidentSummary: string;
  assigneeName?: string;
  status: SmsDeliveryStatus;
  processingStatus: SmsProcessingStatus;
  requestId?: string;
}

export interface ModelMetrics {
  modelVersion: string;
  labelSource: string;
  rocAuc: number;
  precision: number;
  recall: number;
  alertsPerDay: number;
}

export interface AppData {
  demo: boolean;
  objects: RiskObject[];
  alerts: Alert[];
  requests: MaintenanceRequest[];
  sms: SmsNotification[];
  metrics: ModelMetrics;
}
