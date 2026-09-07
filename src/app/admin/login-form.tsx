'use client'

import { useState, type FormEvent } from 'react'
import { createClient } from '@/lib/supabase/client'

type Phase = { kind: 'idle' } | { kind: 'sending' } | { kind: 'sent' } | { kind: 'error'; message: string }

export default function LoginForm() {
  const [email, setEmail] = useState('')
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!email.trim()) return

    setPhase({ kind: 'sending' })
    try {
      const supabase = createClient()
      const { error } = await supabase.auth.signInWithOtp({
        email: email.trim(),
        options: {
          // サインアップは無効。あらかじめ登録済みのユーザーにしかリンクを送らない。
          shouldCreateUser: false,
          emailRedirectTo: `${window.location.origin}/auth/callback?next=/admin`,
        },
      })
      if (error) {
        setPhase({ kind: 'error', message: error.message })
        return
      }
      setPhase({ kind: 'sent' })
    } catch (cause) {
      setPhase({ kind: 'error', message: cause instanceof Error ? cause.message : String(cause) })
    }
  }

  if (phase.kind === 'sent') {
    return (
      <div className="panel">
        <h2>メールを送信しました</h2>
        <p className="note">
          <strong>{email}</strong> 宛のログインリンクを開いてください。リンクは同じ端末・同じ
          ブラウザで開く必要があります。
        </p>
        <p className="note">
          届かない場合は、そのメールアドレスが Supabase にユーザーとして登録されているか確認して
          ください（サインアップは無効化されています）。
        </p>
        <p className="note" style={{ marginTop: 14 }}>
          <button type="button" className="linkButton" onClick={() => setPhase({ kind: 'idle' })}>
            別のメールアドレスで送り直す
          </button>
        </p>
      </div>
    )
  }

  return (
    <form className="panel" onSubmit={onSubmit}>
      <h2>マジックリンクでログイン</h2>
      <label htmlFor="email" style={{ display: 'block', fontSize: 12, fontWeight: 700, marginBottom: 8 }}>
        メールアドレス
      </label>
      <input
        id="email"
        className="textInput"
        type="email"
        inputMode="email"
        autoComplete="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        placeholder="you@example.com"
      />
      <p className="fieldHint">登録済みのアドレスにのみログインリンクを送信します。</p>

      {phase.kind === 'error' ? (
        <p className="fieldHint" style={{ color: '#8f2d1b', fontWeight: 700 }}>
          {phase.message}
        </p>
      ) : null}

      <button className="submit" type="submit" disabled={phase.kind === 'sending'}>
        {phase.kind === 'sending' ? '送信中…' : 'ログインリンクを送る'}
      </button>
    </form>
  )
}
