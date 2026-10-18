// Shared contract between protocol.js (pure logic) and app.js (WebHID wizard UI).
// protocol.js is a classic script: in the browser it sets `window.HECapture`,
// in Node it sets `module.exports`. No ES modules, so index.html works from file://.

export interface KeyLayout {
  id: string;          // "65", "75", "tkl", "full"
  label: string;       // "65% (66 keys)", ...
  keys: string[];      // labels in press order, row by row, left to right.
                       // Labels reuse key_config.json names: ESC, BKSP, LSHIFT, SPACE, UP...
}

export interface ReportItemInfo {
  usagePage: number; usages: number[]; reportSize: number; reportCount: number;
}
export interface ReportInfo { reportId: number; items: ReportItemInfo[]; }
export interface CollectionInfo {
  usagePage: number; usage: number; type: number;
  inputReports: ReportInfo[]; outputReports: ReportInfo[]; featureReports: ReportInfo[];
  children: CollectionInfo[];
}
export interface DeviceInfo {
  index: number; vendorId: number; productId: number; productName: string;
  vid: string; pid: string;   // "0x3151"
  collections: CollectionInfo[];
}

export interface AnalogSample { keyId: number; value: number; }

export interface RawReport { t: number; device: number; reportId: number; hex: string; }
export interface FeatureRead { device: number; reportId: number; hex?: string; error?: string; }

export interface CaptureState {
  userInfo: { model: string; layout: string; notes: string };
  devices: DeviceInfo[];
  featureReads: FeatureRead[];
  analogTest: { attempted: boolean; success: boolean; enabledOn: number[]; reportsSeen: number; error?: string };
  rawLog: RawReport[];               // capped at MAX_RAW_LOG, oldest kept
  rawDropped: number;                // reports discarded after the cap
  keyMapping: Record<string, number>; // label -> key id
  peaks: Record<string, number>;      // label -> max analog value seen
  skipped: string[];
  browserCodes: Record<string, string>; // label -> KeyboardEvent.code seen while mapping
}

export interface HECaptureAPI {
  KNOWN_VENDOR_ID: number;          // 0x3151
  MAX_RAW_LOG: number;              // 2000
  LAYOUTS: KeyLayout[];

  /** 64-byte feature report payload: [0x1B, flag, 0,0,0,0,0, 0xE4 - flag, 0...]. */
  buildCommand(enable: boolean): Uint8Array;
  /** Plain-object snapshot of an HIDDevice (or a lookalike object in tests). */
  describeDevice(device: HIDDevice, index: number): DeviceInfo;
  /** Space-separated lowercase hex, e.g. "1b 05 01". */
  toHex(data: DataView | ArrayBuffer | Uint8Array): string;
  /** WebHID input report data (report ID excluded). null unless data[0] == 0x1B and length >= 4. */
  parseAnalogReport(data: DataView): AnalogSample | null;
  /** Append to state.rawLog respecting MAX_RAW_LOG. */
  pushRaw(state: CaptureState, entry: RawReport): void;
  newState(): CaptureState;
  /** Object with the same shape as the repo's key_config.json. */
  buildKeyConfig(state: CaptureState): object;
  /** Full export: { tool: "he-capture", version: 1, created_at, user_agent, state..., key_config }. */
  buildExport(state: CaptureState, userAgent: string, now: Date): object;
  /** Markdown summary to paste into a GitHub issue. */
  buildIssueSummary(state: CaptureState): string;
}
