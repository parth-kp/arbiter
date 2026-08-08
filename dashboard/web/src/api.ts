import { useCallback, useEffect, useState } from 'react'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') msg = body.detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, msg)
  }
  return res.json() as Promise<T>
}

export function post<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export interface Loaded<T> {
  data: T | null
  error: string | null
  loading: boolean
  reload: () => void
  setData: (d: T | null) => void
}

export function useApi<T>(path: string | null): Loaded<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(path !== null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (path === null) return
    let live = true
    setLoading(true)
    setError(null)
    api<T>(path)
      .then(d => live && setData(d))
      .catch(e => live && (setData(null), setError(e instanceof Error ? e.message : String(e))))
      .finally(() => live && setLoading(false))
    return () => {
      live = false
    }
  }, [path, tick])

  const reload = useCallback(() => setTick(t => t + 1), [])
  return { data, error, loading, reload, setData }
}
