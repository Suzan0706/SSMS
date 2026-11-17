// Dates and times as people in Tanzania read them (East Africa Time), whatever the device's own time zone.
export const todayEat = () => new Date().toLocaleDateString("en-CA", { timeZone: "Africa/Dar_es_Salaam" });

export const clock = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString("en-GB", { timeZone: "Africa/Dar_es_Salaam", hour: "2-digit", minute: "2-digit" }) : "";
