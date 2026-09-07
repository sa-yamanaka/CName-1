import { isSupabaseConfigured } from '@/lib/supabase/env'
import { createClient } from '@/lib/supabase/server'
import { parseProviderStatus } from '@/lib/status'
import LoginForm from './login-form'
import SignOutButton from './sign-out-button'
import StatusForm from './status-form'

export const dynamic = 'force-dynamic'

type PageProps = { searchParams: Promise<Record<string, string | string[] | undefined>> }

export default async function AdminPage({ searchParams }: PageProps) {
  const errorParam = (await searchParams).error
  const loginError = typeof errorParam === 'string' ? errorParam : null

  if (!isSupabaseConfigured()) {
    return (
      <Shell title="Supabase の設定が未完了です">
        <div className="panel">
          <p className="note">
            <code>.env.local</code> に <code>NEXT_PUBLIC_SUPABASE_URL</code> と{' '}
            <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code> を設定してください。
          </p>
        </div>
      </Shell>
    )
  }

  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  // 未ログインならログインフォームへ誘導する。
  if (!user) {
    return (
      <Shell title="管理画面にログイン">
        {loginError ? (
          <div className="panel">
            <p className="note" style={{ color: '#8f2d1b', fontWeight: 700 }}>
              {loginError}
            </p>
          </div>
        ) : null}
        <LoginForm />
      </Shell>
    )
  }

  // ログイン済みでも、許可リストに載っていなければ更新できない。
  const { data: isAdmin } = await supabase.rpc('is_provider_admin')

  if (isAdmin !== true) {
    return (
      <Shell title="権限がありません">
        <div className="panel">
          <p className="note">
            <strong>{user.email}</strong> は更新を許可されたアカウントではありません。
          </p>
          <p className="note">
            Supabase の <code>provider_admins</code> テーブルにこのユーザーを登録すると更新できるようになります
            （<code>supabase/migrations/0002_register_admin.sql.example</code> を参照）。
          </p>
          <p className="note" style={{ marginTop: 16 }}>
            <SignOutButton />
          </p>
        </div>
      </Shell>
    )
  }

  const { data } = await supabase
    .from('provider_status')
    .select('id, status, until_time, next_available, updated_at')
    .eq('id', 1)
    .maybeSingle()

  const initial = parseProviderStatus(data)

  if (!initial) {
    return (
      <Shell title="ステータス行が見つかりません">
        <div className="panel">
          <p className="note">
            <code>provider_status</code> に id = 1 の行がありません。
            <code>supabase/migrations/0001_provider_status.sql</code> を実行してください。
          </p>
        </div>
      </Shell>
    )
  }

  return (
    <Shell title="対応状況の更新" email={user.email ?? undefined}>
      <StatusForm initial={initial} />
    </Shell>
  )
}

function Shell({
  title,
  email,
  children,
}: {
  title: string
  email?: string
  children: React.ReactNode
}) {
  return (
    <div className="sheet">
      <header className="sheetHead">
        <p className="eyebrow">ADMIN</p>
        <h1>{title}</h1>
      </header>
      {children}
      {email ? (
        <p className="note" style={{ marginTop: 20, display: 'flex', gap: 12 }}>
          <span>{email}</span>
          <SignOutButton />
        </p>
      ) : null}
    </div>
  )
}
