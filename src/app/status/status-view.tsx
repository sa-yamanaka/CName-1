'use client'

import { useCallback, useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import {
  formatJstDateTime,
  parseProviderStatus,
  presentStatus,
  type ProviderStatus,
} from '@/lib/status'

/** Realtime が繋がっているときの保険としてのポーリング間隔。 */
const POLL_MS_CONNECTED = 60_000
/** Realtime が使えないときのポーリング間隔。 */
const POLL_MS_FALLBACK = 30_000

type Props = {
  initial: ProviderStatus | null
  initialError: string | null
  /** SSR と最初のクライアント描画を一致させるためのサーバー時刻。 */
  serverNow: string
}

export default function StatusView({ initial, initialError, serverNow }: Props) {
  const [row, setRow] = useState<ProviderStatus | null>(initial)
  const [error, setError] = useState<string | null>(initialError)
  const [live, setLive] = useState(false)
  // 初回描画はサーバー時刻を使い、マウント後にクライアント時刻へ切り替える。
  const [now, setNow] = useState(() => new Date(serverNow))

  const refresh = useCallback(async () => {
    try {
      const supabase = createClient()
      const { data, error: fetchError } = await supabase
        .from('provider_status')
        .select('id, status, until_time, next_available, updated_at')
        .eq('id', 1)
        .maybeSingle()

      if (fetchError) {
        setError(fetchError.message)
        return
      }
      const next = parseProviderStatus(data)
      if (next) {
        setRow(next)
        setError(null)
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }, [])

  // 時刻超過（延長中）の判定を進めるため、現在時刻を定期的に更新する。
  useEffect(() => {
    setNow(new Date())
    const timer = window.setInterval(() => setNow(new Date()), 20_000)
    return () => window.clearInterval(timer)
  }, [])

  // Realtime 購読。
  useEffect(() => {
    const supabase = createClient()
    const channel = supabase
      .channel('provider_status_public')
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'provider_status' },
        (payload: { new?: unknown }) => {
          const next = parseProviderStatus(payload.new)
          if (next) {
            setRow(next)
            setError(null)
          } else {
            void refresh()
          }
        },
      )
      .subscribe((status: string) => setLive(status === 'SUBSCRIBED'))

    return () => {
      void supabase.removeChannel(channel)
    }
  }, [refresh])

  // ポーリング（Realtime が無効・切断されている場合の保険）。
  useEffect(() => {
    const interval = live ? POLL_MS_CONNECTED : POLL_MS_FALLBACK
    const timer = window.setInterval(() => void refresh(), interval)
    return () => window.clearInterval(timer)
  }, [live, refresh])

  // LINE 内ブラウザはタブを戻したときに時間が飛んでいることがあるので取り直す。
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        setNow(new Date())
        void refresh()
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', onVisible)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', onVisible)
    }
  }, [refresh])

  if (!row) {
    return (
      <div className="statusScreen" data-tone="">
        <main className="statusMain">
          <p className="statusHeadline">読み込み中</p>
          <p className="statusDetail">
            {error ?? '状態を取得しています。しばらくお待ちください。'}
          </p>
        </main>
      </div>
    )
  }

  const view = presentStatus(row, now)

  return (
    <div className="statusScreen" data-tone={view.tone}>
      <main className="statusMain">
        <p className="statusBadge">
          <span className="statusDot" aria-hidden="true" />
          ただいまの状況
        </p>
        <h1 className="statusHeadline">{view.headline}</h1>
        {view.detail ? <p className="statusDetail statusTime">{view.detail}</p> : null}
      </main>

      <footer className="statusFoot">
        <span className="statusTime">最終更新 {formatJstDateTime(row.updated_at)}</span>
        <span className="live">
          <span className="liveDot" data-live={live} aria-hidden="true" />
          {live ? '自動更新中' : '30秒ごとに更新'}
        </span>
      </footer>
    </div>
  )
}
