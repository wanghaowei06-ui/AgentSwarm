import type { JsonObject } from "../types";

export type MatrixEvent = {
  event_id: string;
  room_id: string;
  sender: string;
  origin_server_ts: number;
  type: string;
  content: JsonObject;
  unsigned?: JsonObject;
};

export type MatrixStateEvent = {
  type: string;
  state_key?: string;
  content: JsonObject;
};
