import { Navigate, Outlet, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

export default function ProtectedRoute({ roles }) {
  const { user, loading } = useAuth()
  const params = useParams()

  if (loading) return <main className="auth-loading">Checking your session…</main>
  if (!user) return <Navigate to="/login" replace />
  if (params.role && params.role !== user.role) return <Navigate to={`/app/${user.role}/tickets`} replace />
  if (roles && !roles.includes(user.role)) return <Navigate to={`/app/${user.role}`} replace />
  return <Outlet />
}
