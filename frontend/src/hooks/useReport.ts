import { useEffect, useState } from "react"

import { isApiError } from "@/api/auth"

/**
 * Fetch one report for a chart on the Charts tab. `load` runs again whenever
 * it changes, so wrap it in useCallback over its arguments; it returns null to
 * skip a fetch (an emptied date input, say), keeping what was shown. A reply to
 * a superseded load is dropped. `data` is null until the first reply.
 */
export function useReport<T>(load: () => Promise<T> | null, failure: string) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const pending = load()
    if (pending === null) return
    let stale = false
    pending
      .then((result) => {
        if (stale) return
        setData(result)
        setError(null)
      })
      .catch((err: unknown) => {
        if (stale) return
        setError(isApiError(err) ? err.message : failure)
      })
    return () => {
      stale = true
    }
  }, [load, failure])

  return { data, error }
}
