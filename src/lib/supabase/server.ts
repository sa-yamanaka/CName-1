import { cookies } from 'next/headers'
import { createServerClient } from '@supabase/ssr'
import { createClient as createSupabaseClient } from '@supabase/supabase-js'
import { supabaseEnv } from './env'

/**
 * リクエスト単位のサーバークライアント。Cookie からセッションを読む。
 * Server Component からは Cookie を書けないため setAll は握りつぶし、
 * トークンの更新は proxy.ts に任せる。
 */
export async function createClient() {
  const { url, anonKey } = supabaseEnv()
  const cookieStore = await cookies()

  return createServerClient(url, anonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll()
      },
      setAll(cookiesToSet) {
        try {
          for (const { name, value, options } of cookiesToSet) {
            cookieStore.set(name, value, options)
          }
        } catch {
          // Server Component から呼ばれた場合はここに来る。proxy.ts が更新するので無視してよい。
        }
      },
    },
  })
}

/**
 * 認証を伴わない読み取り専用クライアント。公開ページ用。
 * Cookie を触らないので、ログイン状態に関係なく anon 権限で読める。
 */
export function createPublicClient() {
  const { url, anonKey } = supabaseEnv()
  return createSupabaseClient(url, anonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  })
}
