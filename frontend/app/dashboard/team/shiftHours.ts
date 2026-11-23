export interface ShiftConfig {
  shift_mode: "common" | "individual";
  shift_start_hour: number;
  shift_end_hour: number;
}

/** 9 -> "09:00". */
export function formatHour(h: number): string {
  return `${h.toString().padStart(2, "0")}:00`;
}

/** The shift that applies to one person: their own hours in "one per person" mode when set, else the shared shift. */
export function effectiveShift(
  config: ShiftConfig,
  person: { shift_start_hour?: number | null; shift_end_hour?: number | null } | null | undefined,
): { start: number; end: number } {
  const own = config.shift_mode === "individual";
  return {
    start: own && person?.shift_start_hour != null ? person.shift_start_hour : config.shift_start_hour,
    end: own && person?.shift_end_hour != null ? person.shift_end_hour : config.shift_end_hour,
  };
}
