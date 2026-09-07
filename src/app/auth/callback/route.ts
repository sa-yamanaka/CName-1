import { NextResponse, type NextRequest } from 'next/server'
import type { EmailOtpType } from '@supabase/supabase-js'
import { createClient } from '@/lib/supabase/server'

/**
 * マジックリンクの着地点。Supabase の設定によって `code`（PKCE）と
 * `token_hash`（旧来のリンク）のどちらかが付いてくるので両方を受ける。
 */
export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl
  const next = safeNext(searchParams.get('next'))

  // Supabase 側で弾かれた場合はそのまま理由を持って戻す。
  const providerError = searchParams.get('error_description') ?? searchParams.get('error')
  if (providerError) {
    return redirectWithError(request, next, providerError)
  }

  const code = searchParams.get('code')
  const tokenHash = searchParams.get('token_hash')
  const type = searchParams.get('type') as EmailOtpType | null

  const supabase = await createClient()

  if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code)
    if (error) return redirectWithError(request, next, error.message)
    return NextResponse.redirect(new URL(next, request.url))
  }

  if (tokenHash && type) {
    const { error } = await supabase.auth.verifyOtp({ type, token_hash: tokenHash })
    if (error) return redirectWithError(request, next, error.message)
    return NextResponse.redirect(new URL(next, request.url))
  }

  return redirectWithError(request, next, 'ログインリンクが正しくありません。')
}

/** オープンリダイレクトを避けるため、自サイト内の絶対パスだけを許可する。 */
function safeNext(value: string | null): string {
  if (!value) return '/admin'
  if (!value.startsWith('/') || value.startsWith('//')) return '/admin'
  return value
}

function redirectWithError(request: NextRequest, next: string, message: string) {
  const url = new URL(next, request.url)
  url.searchParams.set('error', message)
  return NextResponse.redirect(url)
}
