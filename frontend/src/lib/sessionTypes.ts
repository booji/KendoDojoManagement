import type { Segment, SessionType } from "@/api/sessions"

/**
 * Returns the distinct session types referenced across a session's segments,
 * in first-seen order. Unknown type ids (not present in typeMap) are skipped.
 */
export const distinctSessionTypes = (
  segments: Segment[],
  typeMap: Map<string, SessionType>,
): SessionType[] => {
  const seen = new Set<string>()
  const result: SessionType[] = []
  for (const segment of segments) {
    for (const typeId of segment.type_ids) {
      if (seen.has(typeId)) continue
      const type = typeMap.get(typeId)
      if (type === undefined) continue
      seen.add(typeId)
      result.push(type)
    }
  }
  return result
}
