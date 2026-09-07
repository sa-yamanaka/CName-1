import { NextResponse, type NextRequest } from 'next/server'
import { createServerClient } from '@supabase/ssr'
import { isSupabaseConfigured, supabaseEnv } from '@/lib/supabase/env'

/**
 * Next.js 16 の proxy（旧 middleware）。
 * 期限切れが近い Supabase のアクセストークンを更新し、新しい Cookie を
 * リクエストとレスポンスの両方に書き戻す。これをしないと Server Component
 * 側のセッションが 1 時間ほどで切れてしまう。
 */
export async function proxy(request: NextRequest) {
  if (!isSupabaseConfigured()) return NextResponse.next()

  let response = NextResponse.next({ request })
  const { url, anonKey } = supabaseEnv()

  const supabase = createServerClient(url, anonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll()
      },
      setAll(cookiesToSet, headers) {
        for (const { name, value } of cookiesToSet) {
          request.cookies.set(name, value)
        }
        response = NextResponse.next({ request })
        for (const { name, value, options } of cookiesToSet) {
          response.cookies.set(name, value, options)
        }
        for (const [key, headerValue] of Object.entries(headers)) {
          response.headers.set(key, headerValue)
        }
      },
    },
  })

  // getUser() を呼ぶとトークンの更新が走る。戻り値はここでは使わない。
  await supabase.auth.getUser()

  return response
}

export const config = {
  matcher: [
    /*
     * 静的アセットと画像最適化のリクエストは除外する。
     */
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)',
  ],
}
