export const STATUS_VALUES = ['busy', 'break', 'available'] as const

export type StatusValue = (typeof STATUS_VALUES)[number]

export type ProviderStatus = {
  id: number
  status: StatusValue
  until_time: string | null
  next_available: string | null
  updated_at: string
}

export const STATUS_LABELS: Record<StatusValue, string> = {
  busy: '対応中',
  break: '休憩中',
  available: '空き',
}

export function isStatusValue(value: unknown): value is StatusValue {
  return typeof value === 'string' && (STATUS_VALUES as readonly string[]).includes(value)
}

/** 日本はサマータイムがないため UTC+9 の固定オフセットで扱える。 */
const JST_OFFSET_MS = 9 * 60 * 60 * 1000

/** JST の壁時計（年月日時分）を UTC の瞬間に変換する。 */
export function jstWallClockToDate(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number,
): Date {
  return new Date(Date.UTC(year, month - 1, day, hour, minute) - JST_OFFSET_MS)
}

/** ある瞬間を JST の壁時計に分解する。 */
export function toJstParts(date: Date) {
  const shifted = new Date(date.getTime() + JST_OFFSET_MS)
  return {
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth() + 1,
    day: shifted.getUTCDate(),
    hour: shifted.getUTCHours(),
    minute: shifted.getUTCMinutes(),
  }
}

const TIME_FORMATTER = new Intl.DateTimeFormat('ja-JP', {
  timeZone: 'Asia/Tokyo',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

const DATE_TIME_FORMATTER = new Intl.DateTimeFormat('ja-JP', {
  timeZone: 'Asia/Tokyo',
  month: 'numeric',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

/** "14:30" 形式。サーバー・クライアントどちらでも同じ文字列になる。 */
export function formatJstTime(iso: string): string {
  return TIME_FORMATTER.format(new Date(iso))
}

/** "9/7 14:30" 形式。 */
export function formatJstDateTime(iso: string): string {
  return DATE_TIME_FORMATTER.format(new Date(iso))
}

/** 表示に使う色調。CSS 側の data-tone と対応する。 */
export type StatusTone = 'busy' | 'overrun' | 'break' | 'available'

export type StatusPresentation = {
  tone: StatusTone
  /** 大きく出す見出し。 */
  headline: string
  /** 見出しの下に添える補足。不要なら null。 */
  detail: string | null
}

/**
 * 保存されている行を、公開ページに出す文言に変換する。
 * `now` を渡せるようにしてあるのは、時刻超過の分岐をテストしやすくするため。
 */
export function presentStatus(
  row: ProviderStatus,
  now: Date = new Date(),
): StatusPresentation {
  switch (row.status) {
    case 'busy': {
      if (!row.until_time) {
        return { tone: 'busy', headline: '対応中', detail: '終了予定は未設定です' }
      }
      const until = new Date(row.until_time)
      if (now.getTime() > until.getTime()) {
        return {
          tone: 'overrun',
          headline: '対応中（延長中）',
          detail: `${formatJstTime(row.until_time)} までの予定を過ぎています`,
        }
      }
      return {
        tone: 'busy',
        headline: '対応中',
        detail: `${formatJstTime(row.until_time)} まで`,
      }
    }
    case 'break': {
      if (!row.next_available) {
        return { tone: 'break', headline: '休憩中', detail: '再開時刻は未定です' }
      }
      const next = new Date(row.next_available)
      if (now.getTime() > next.getTime()) {
        return {
          tone: 'break',
          headline: '休憩中',
          detail: `${formatJstTime(row.next_available)} 予定・まもなく再開します`,
        }
      }
      return {
        tone: 'break',
        headline: '休憩中',
        detail: `${formatJstTime(row.next_available)} から対応可能`,
      }
    }
    case 'available':
    default:
      return { tone: 'available', headline: '対応可能です', detail: 'お気軽にご連絡ください' }
  }
}

/** DB から返ってきた任意の値を ProviderStatus として検証する。 */
export function parseProviderStatus(value: unknown): ProviderStatus | null {
  if (!value || typeof value !== 'object') return null
  const row = value as Record<string, unknown>
  if (!isStatusValue(row.status)) return null
  if (typeof row.updated_at !== 'string') return null
  return {
    id: typeof row.id === 'number' ? row.id : 1,
    status: row.status,
    until_time: typeof row.until_time === 'string' ? row.until_time : null,
    next_available: typeof row.next_available === 'string' ? row.next_available : null,
    updated_at: row.updated_at,
  }
}

// ---------------------------------------------------------------------------
// 管理画面の時刻入力（<input type="time"> の "HH:MM"）と timestamptz の変換
// ---------------------------------------------------------------------------

const DAY_MS = 24 * 60 * 60 * 1000

function pad2(value: number): string {
  return String(value).padStart(2, '0')
}

/** timestamptz を JST の "HH:MM" に変換する。 */
export function isoToTimeInput(iso: string | null): string {
  if (!iso) return ''
  const parts = toJstParts(new Date(iso))
  return `${pad2(parts.hour)}:${pad2(parts.minute)}`
}

/**
 * "HH:MM"（JST の壁時計）を timestamptz に変換する。
 * 入力が現在時刻より前なら翌日の同時刻とみなす（深夜またぎ対応）。
 */
export function timeInputToIso(value: string, now: Date = new Date()): string | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim())
  if (!match) return null

  const hour = Number(match[1])
  const minute = Number(match[2])
  if (hour > 23 || minute > 59) return null

  const today = toJstParts(now)
  let target = jstWallClockToDate(today.year, today.month, today.day, hour, minute)

  // 1 分の余裕を持たせて、ちょうど現在時刻を指定した場合に翌日へ飛ばさない。
  if (target.getTime() < now.getTime() - 60_000) {
    target = new Date(target.getTime() + DAY_MS)
  }
  return target.toISOString()
}

/** 現在から `minutes` 後を 15 分単位に切り上げた "HH:MM" を返す。 */
export function roundedTimeInput(minutes: number, now: Date = new Date()): string {
  const target = new Date(now.getTime() + minutes * 60_000)
  const parts = toJstParts(target)
  const rounded = (Math.ceil((parts.hour * 60 + parts.minute) / 15) * 15) % (24 * 60)
  return `${pad2(Math.floor(rounded / 60))}:${pad2(rounded % 60)}`
}
