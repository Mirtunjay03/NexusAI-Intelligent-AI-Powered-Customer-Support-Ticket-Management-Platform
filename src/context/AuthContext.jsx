import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { apiRequest } from '../services/api.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    apiRequest('/api/auth/me')
      .then((currentUser) => {
        if (active) setUser(currentUser)
      })
      .catch(() => {
        if (active) setUser(null)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [])

  const register = useCallback(async (form) => {
    const result = await apiRequest('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify(form),
    })
    setUser(result.user)
    return result.user
  }, [])

  const login = useCallback(async (form) => {
    const result = await apiRequest('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify(form),
    })
    setUser(result.user)
    return result.user
  }, [])

  const logout = useCallback(async () => {
    await apiRequest('/api/auth/logout', { method: 'POST' })
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, loading, register, login, logout }),
    [user, loading, register, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
