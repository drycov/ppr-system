import React, { useEffect, useState } from 'react'

const API = '/api'

export default function App() {
  const [token, setToken] = useState(localStorage.getItem('token') || '')
  const [stats, setStats] = useState(null)
  const [user, setUser] = useState('')
  const [pass, setPass] = useState('')
  const [error, setError] = useState('')

  async function login(e) {
    e.preventDefault()
    setError('')
    const body = new URLSearchParams({ username: user, password: pass })
    const r = await fetch(API + '/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body
    })
    if (!r.ok) { setError('Ошибка входа'); return }
    const data = await r.json()
    localStorage.setItem('token', data.access_token)
    setToken(data.access_token)
  }

  useEffect(() => {
    if (!token) return
    fetch(API + '/stats/completion', { headers: { Authorization: 'Bearer ' + token } })
      .then(r => r.ok ? r.json() : null)
      .then(setStats)
      .catch(() => {})
  }, [token])

  if (!token) {
    return (
      <div style={{ maxWidth: 360, margin: '80px auto', fontFamily: 'system-ui' }}>
        <h1>ППР ОСС (React)</h1>
        <p style={{ color: '#64748b' }}>Каркас UI. Основной интерфейс — backend/static.</p>
        <form onSubmit={login}>
          <input placeholder="Логин" value={user} onChange={e => setUser(e.target.value)} style={{ display: 'block', width: '100%', marginBottom: 8 }} />
          <input placeholder="Пароль" type="password" value={pass} onChange={e => setPass(e.target.value)} style={{ display: 'block', width: '100%', marginBottom: 8 }} />
          <button type="submit">Войти</button>
          {error && <p style={{ color: 'crimson' }}>{error}</p>}
        </form>
      </div>
    )
  }

  return (
    <div style={{ fontFamily: 'system-ui', padding: 24 }}>
      <h1>ППР ОСС — React каркас</h1>
      <button onClick={() => { localStorage.removeItem('token'); setToken('') }}>Выйти</button>
      <pre style={{ background: '#f1f5f9', padding: 12, marginTop: 16 }}>
        {stats ? JSON.stringify(stats, null, 2) : 'Загрузка статистики…'}
      </pre>
      <p>Дальнейшая миграция экранов — по мере необходимости. Рабочий SPA: <code>/</code> (FastAPI static).</p>
    </div>
  )
}
