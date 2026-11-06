export interface TariffInfo {
  name: string;
  price_per_minute: number;
  free_minutes: number;
}

export interface EntryDisplayUpdateEvent {
  event: "entry_display_update";
  free_slots?: number;
  total_slots?: number;
  free_paid_slots: number;
  total_paid_slots: number;
  free_employee_slots: number;
  total_employee_slots: number;
  tariff: TariffInfo | null;
}

export interface BarrierOpenEvent {
  event: "barrier_open";
  plate_number: string;
  gate: "entry" | "exit";
}

export type EntryDisplayEvent = EntryDisplayUpdateEvent | BarrierOpenEvent;


export interface ExitBillEvent {
  event: "exit_bill";
  session_id: number;
  plate_number: string;
  duration: { hours: number; minutes: number; seconds: number };
  amount_due: number;
  pay_url: string;
  qr_code_base64: string;
  status: string;
}

export interface ExitClearEvent {
  event: "exit_clear";
}

export type ExitDisplayEvent = ExitBillEvent | BarrierOpenEvent | ExitClearEvent;
