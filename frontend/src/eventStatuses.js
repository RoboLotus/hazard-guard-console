export function mergeEventStatuses(current, incoming) {
  if (current?.map_id !== incoming.map_id) return incoming;
  const rows = new Map((current.statuses || []).map((row) => [JSON.stringify([row.id, row.level]), row]));
  for (const row of incoming.statuses || []) {
    const key = JSON.stringify([row.id, row.level]);
    if (!rows.has(key) || row.revision >= rows.get(key).revision) rows.set(key, row);
  }
  return { map_id: incoming.map_id, statuses: [...rows.values()] };
}

export function applyEventStatuses(events, stored, mapId) {
  if (stored?.map_id !== mapId) return events;
  return events.map((event) => {
    const row = stored.statuses?.find((item) => item.id === event.id && item.level === event.level);
    if (!row) return event;
    return { ...event, status: row.status, acknowledged: row.status !== "new", assignee: row.status === "new" ? "미지정" : "관리자" };
  });
}
