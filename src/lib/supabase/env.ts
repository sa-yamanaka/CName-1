type SupabaseEnv = { url: string; anonKey: string }

/**
 * 環境変数を読む。ビルド時ではなく実行時に投げるので、
 * 環境変数が未設定でも `next build` は通る。
 */
export function supabaseEnv(): SupabaseEnv {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

  if (!url || !anonKey) {
    throw new Error(
      'NEXT_PUBLIC_SUPABASE_URL と NEXT_PUBLIC_SUPABASE_ANON_KEY を設定してください（.env.local.example を参照）。',
    )
  }
  return { url, anonKey }
}

/** 設定済みかどうかだけを確認する（画面に設定手順を出すため）。 */
export function isSupabaseConfigured(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY)
}
