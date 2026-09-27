export type RiskLevel = "black" | "red" | "yellow" | "green";
export type AlertKind = "fire" | "malfunction";
export type RequestStatus = "new" | "under_review" | "scheduled" | "in_progress" | "completed" | "rejected";

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

export interface MaintenanceRequest {
  id: string;
  alertId: string;
  objectId: string;
  objectName: string;
  picket?: string;
  recommendation: string;
  status: RequestStatus;
  createdAt: string;
  updatedAt: string;
}

export interface SmsNotification {
  id: string;
  episodeId: string;
  alertLevel: RiskLevel;
  recipientId: string;
  role: string;
  sentAt: string;
  content: string;
  status: "queued" | "delivered" | "failed";
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
