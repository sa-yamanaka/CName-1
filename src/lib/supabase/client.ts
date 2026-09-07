'use client'

import { createBrowserClient } from '@supabase/ssr'
import { supabaseEnv } from './env'

let cached: ReturnType<typeof createBrowserClient> | null = null

/** ブラウザ側クライアント。セッションは Cookie に保存されサーバーからも読める。 */
export function createClient() {
  if (!cached) {
    const { url, anonKey } = supabaseEnv()
    cached = createBrowserClient(url, anonKey)
  }
  return cached
}
