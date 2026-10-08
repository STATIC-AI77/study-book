import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { supabase, isSupabaseConfigured } from '@/lib/supabase/client'
import type { UserProfile } from '@/lib/types/auth'

interface AuthState {
  isAuthenticated: boolean
  token: string | null
  user: UserProfile | null
  isLoading: boolean
  error: string | null
  hasHydrated: boolean
  setHasHydrated: (state: boolean) => void
  setAuthSession: (token: string, user?: UserProfile | null) => void
  logout: () => Promise<void>
  checkAuth: () => Promise<boolean>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      isAuthenticated: false,
      token: null,
      user: null,
      isLoading: false,
      error: null,
      hasHydrated: false,

      setHasHydrated: (state: boolean) => {
        set({ hasHydrated: state })
      },

      setAuthSession: (token: string, user?: UserProfile | null) => {
        set({
          isAuthenticated: true,
          token,
          user: user || null,
          error: null,
          isLoading: false,
        })
      },

      logout: async () => {
        try {
          if (isSupabaseConfigured()) {
            await supabase.auth.signOut()
          }
        } catch (err) {
          console.error('Error signing out of Supabase:', err)
        }

        if (typeof window !== 'undefined') {
          window.localStorage.removeItem('auth-storage')
          try {
            const keysToRemove: string[] = []
            for (let i = 0; i < window.localStorage.length; i++) {
              const key = window.localStorage.key(i)
              if (key && key.startsWith('sb-')) {
                keysToRemove.push(key)
              }
            }
            keysToRemove.forEach((key) => window.localStorage.removeItem(key))
          } catch {
            // Ignore storage access errors
          }
        }

        set({
          isAuthenticated: false,
          token: null,
          user: null,
          error: null,
          isLoading: false,
        })
      },

      checkAuth: async () => {
        if (!isSupabaseConfigured()) {
          set({ isAuthenticated: false, token: null, user: null, isLoading: false })
          return false
        }

        try {
          const { data, error } = await supabase.auth.getSession()
          if (error || !data.session?.access_token) {
            set({ isAuthenticated: false, token: null, user: null, isLoading: false })
            return false
          }

          const sbUser = data.session.user
          const userProfile: UserProfile = {
            email: sbUser?.email || null,
            avatarUrl: sbUser?.user_metadata?.avatar_url || sbUser?.user_metadata?.picture || null,
            name: sbUser?.user_metadata?.full_name || sbUser?.user_metadata?.name || null,
          }

          set({
            isAuthenticated: true,
            token: data.session.access_token,
            user: userProfile,
            error: null,
            isLoading: false,
          })
          return true
        } catch (err) {
          console.error('Error checking Supabase auth:', err)
          set({ isAuthenticated: false, token: null, user: null, isLoading: false })
          return false
        }
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({
        token: state.token,
        isAuthenticated: state.isAuthenticated,
        user: state.user,
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true)
      },
    }
  )
)