import { isSupabaseConfigured } from '@/lib/supabase/env'
import { createPublicClient } from '@/lib/supabase/server'
import { parseProviderStatus } from '@/lib/status'
import StatusView from './status-view'

/** 常に最新の状態を取りに行く（キャッシュさせない）。 */
export const dynamic = 'force-dynamic'

export default async function StatusPage() {
  if (!isSupabaseConfigured()) {
    return <SetupNotice />
  }

  // Supabase に届かなくても公開ページを 500 にしない。
  // 取得できなかった場合はクライアント側の再取得に任せる。
  let initial = null
  let initialError: string | null = null

  try {
    const supabase = createPublicClient()
    const { data, error } = await supabase
      .from('provider_status')
      .select('id, status, until_time, next_available, updated_at')
      .eq('id', 1)
      .maybeSingle()

    initial = parseProviderStatus(data)
    initialError = error ? error.message : null
  } catch (cause) {
    initialError = cause instanceof Error ? cause.message : String(cause)
  }

  return (
    <StatusView
      initial={initial}
      initialError={initialError}
      serverNow={new Date().toISOString()}
    />
  )
}

function SetupNotice() {
  return (
    <div className="sheet">
      <div className="sheetHead">
        <p className="eyebrow">SETUP</p>
        <h1>Supabase の設定が未完了です</h1>
      </div>
      <div className="panel">
        <p className="note">
          <code>.env.local</code> に <code>NEXT_PUBLIC_SUPABASE_URL</code> と{' '}
          <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code> を設定してください。
        </p>
        <p className="note">
          Vercel にデプロイしている場合は、プロジェクトの Settings &gt; Environment Variables
          に同じ 2 つを登録して再デプロイします。
        </p>
      </div>
    </div>
  )
}
