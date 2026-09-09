'use client'

import { useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import {
  STATUS_LABELS,
  formatJstDateTime,
  formatJstTime,
  isoToTimeInput,
  parseProviderStatus,
  roundedTimeInput,
  timeInputToIso,
  type ProviderStatus,
  type StatusValue,
} from '@/lib/status'

const CHOICES: { value: StatusValue; hint: string }[] = [
  { value: 'busy', hint: '終了予定の時刻を指定します' },
  { value: 'break', hint: '次に対応できる時刻を指定します' },
  { value: 'available', hint: 'タップすると即時反映されます' },
]

/** 時刻入力のショートカット（現在時刻からの分数）。 */
const QUICK_OFFSETS = [15, 30, 60, 120]

type Toast = { kind: 'success' | 'error'; message: string }

export default function StatusForm({ initial }: { initial: ProviderStatus }) {
  const [row, setRow] = useState(initial)
  const [selected, setSelected] = useState<StatusValue>(initial.status)
  const [untilTime, setUntilTime] = useState(() =>
    initial.status === 'busy' ? isoToTimeInput(initial.until_time) : '',
  )
  const [nextTime, setNextTime] = useState(() =>
    initial.status === 'break' ? isoToTimeInput(initial.next_available) : '',
  )
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<Toast | null>(null)

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 4000)
    return () => window.clearTimeout(timer)
  }, [toast])

  async function save(next: StatusValue) {
    let untilIso: string | null = null
    let nextIso: string | null = null

    if (next === 'busy') {
      untilIso = timeInputToIso(untilTime)
      if (!untilIso) {
        setToast({ kind: 'error', message: '終了予定の時刻を入力してください' })
        return
      }
    }
    if (next === 'break') {
      nextIso = timeInputToIso(nextTime)
      if (!nextIso) {
        setToast({ kind: 'error', message: '次に対応できる時刻を入力してください' })
        return
      }
    }

    setSaving(true)
    try {
      const supabase = createClient()
      const { data, error } = await supabase
        .from('provider_status')
        // updated_at は DB のトリガーが打ち直すので送らない。
        .update({ status: next, until_time: untilIso, next_available: nextIso })
        .eq('id', 1)
        .select('id, status, until_time, next_available, updated_at')
        .maybeSingle()

      if (error) {
        setToast({ kind: 'error', message: `更新に失敗しました: ${error.message}` })
        return
      }

      const updated = parseProviderStatus(data)
      if (!updated) {
        // RLS で弾かれると 0 行が返る（エラーにはならない）。
        setToast({ kind: 'error', message: '更新できませんでした。アカウントの権限を確認してください。' })
        return
      }

      setRow(updated)
      setSelected(updated.status)
      setToast({ kind: 'success', message: `「${STATUS_LABELS[next]}」に更新しました` })
    } catch (cause) {
      setToast({
        kind: 'error',
        message: cause instanceof Error ? cause.message : String(cause),
      })
    } finally {
      setSaving(false)
    }
  }

  function choose(value: StatusValue) {
    setSelected(value)
    // 「空き」は時刻入力が不要なので、その場で反映する。
    if (value === 'available') {
      void save('available')
      return
    }
    if (value === 'busy' && !untilTime) setUntilTime(roundedTimeInput(60))
    if (value === 'break' && !nextTime) setNextTime(roundedTimeInput(30))
  }

  return (
    <>
      <div className="current">
        <span className="currentValue">現在：{describe(row)}</span>
        <span className="currentMeta">{formatJstDateTime(row.updated_at)} 更新</span>
      </div>

      <div className="panel">
        <h2>状態を選ぶ</h2>
        <div className="choices">
          {CHOICES.map((choice) => (
            <button
              key={choice.value}
              type="button"
              className="choice"
              data-value={choice.value}
              aria-pressed={selected === choice.value}
              disabled={saving}
              onClick={() => choose(choice.value)}
            >
              <span className="swatch" aria-hidden="true" />
              <span className="choiceText">
                <span className="choiceName">{STATUS_LABELS[choice.value]}</span>
                <span className="choiceHint">{choice.hint}</span>
              </span>
            </button>
          ))}
        </div>

        {selected === 'busy' ? (
          <TimeField
            id="until"
            label="何時まで対応中か"
            value={untilTime}
            onChange={setUntilTime}
            disabled={saving}
          />
        ) : null}

        {selected === 'break' ? (
          <TimeField
            id="next"
            label="次に対応できるのは何時からか"
            value={nextTime}
            onChange={setNextTime}
            disabled={saving}
          />
        ) : null}

        {selected === 'available' ? (
          <p className="fieldHint">「空き」は選んだ時点で反映されます。</p>
        ) : (
          <button className="submit" type="button" disabled={saving} onClick={() => void save(selected)}>
            {saving ? '更新中…' : `「${STATUS_LABELS[selected]}」で更新する`}
          </button>
        )}
      </div>

      <p className="note" style={{ marginTop: 16 }}>
        公開ページ：<a href="/status">/status</a>
      </p>

      {toast ? (
        <div className="toast" data-kind={toast.kind} role="status" aria-live="polite">
          {toast.message}
        </div>
      ) : null}
    </>
  )
}

function TimeField({
  id,
  label,
  value,
  onChange,
  disabled,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  disabled: boolean
}) {
  return (
    <div className="timeField">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="time"
        step={900}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
      <div className="quick">
        {QUICK_OFFSETS.map((minutes) => (
          <button
            key={minutes}
            type="button"
            disabled={disabled}
            onClick={() => onChange(roundedTimeInput(minutes))}
          >
            {minutes < 60 ? `+${minutes}分` : `+${minutes / 60}時間`}
          </button>
        ))}
      </div>
      <p className="fieldHint">
        15 分刻みで指定できます。現在より前の時刻を入れた場合は翌日として扱います。
      </p>
    </div>
  )
}

/** 管理画面のサマリー表示。現在時刻に依存しないので SSR と一致する。 */
function describe(row: ProviderStatus): string {
  switch (row.status) {
    case 'busy':
      return row.until_time ? `対応中（${formatJstTime(row.until_time)} まで）` : '対応中'
    case 'break':
      return row.next_available ? `休憩中（${formatJstTime(row.next_available)} から）` : '休憩中'
    default:
      return '空き'
  }
}
