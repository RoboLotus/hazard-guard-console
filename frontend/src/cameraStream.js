export function cameraStreamState(stream) {
  const source = typeof stream?.source === "string" ? stream.source : "";
  const simulated = source.startsWith("gazebo:") || source.startsWith("simulation:");
  const supported = simulated || source.startsWith("ros:");
  const available = Boolean(stream?.available && !stream?.stale && supported);
  return { available, source, simulated };
}
