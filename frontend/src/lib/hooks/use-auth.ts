'use client'

import { useAuthStore } from '@/lib/stores/auth-store'
import { useRouter } from 'next/navigation'
import { useEffect, useState, useCallback } from 'react'
import { supabase, isSupabaseConfigured } from '@/lib/supabase/client'
import type { UserProfile } from '@/lib/types/auth'

export function useAuth() {
  const router = useRouter()
  const {
    isAuthenticated,
    token,
    user,
    isLoading,
    setAuthSession,
    logout,
    checkAuth,
    error,
    hasHydrated,
  } = useAuthStore()

  const [isVerifying, setIsVerifying] = useState(true)

  useEffect(() => {
    let mounted = true

    if (hasHydrated) {
      checkAuth().finally(() => {
        if (mounted) setIsVerifying(false)
      })
    }

    let subscription: { unsubscribe: () => void } | null = null
    if (isSupabaseConfigured()) {
      const { data } = supabase.auth.onAuthStateChange((event, session) => {
        if (session?.access_token) {
          const sbUser = session.user
          const userProfile: UserProfile = {
            email: sbUser?.email || null,
            avatarUrl: sbUser?.user_metadata?.avatar_url || sbUser?.user_metadata?.picture || null,
            name: sbUser?.user_metadata?.full_name || sbUser?.user_metadata?.name || null,
          }
          setAuthSession(session.access_token, userProfile)
        } else if (event === 'SIGNED_OUT') {
          useAuthStore.setState({ isAuthenticated: false, token: null, user: null })
        }
      })
      subscription = data.subscription
    }

    return () => {
      mounted = false
      subscription?.unsubscribe()
    }
  }, [hasHydrated, checkAuth, setAuthSession])

  const handleLogout = useCallback(async () => {
    await logout()
    if (typeof window !== 'undefined') {
      window.location.href = '/login'
    } else {
      router.push('/login')
    }
  }, [logout, router])

  const isSessionValid = isAuthenticated && Boolean(token) && token !== 'not-required'

  return {
    isAuthenticated: isSessionValid,
    token,
    user,
    isLoading: isLoading || !hasHydrated || isVerifying,
    error,
    logout: handleLogout,
    checkAuth,
    setAuthSession,
  }
}