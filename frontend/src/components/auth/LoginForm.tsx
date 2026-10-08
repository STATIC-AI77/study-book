'use client'

import { useState, useEffect, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useAuthStore } from '@/lib/stores/auth-store'
import { getConfig } from '@/lib/config'
import { isSupabaseConfigured, supabase } from '@/lib/supabase/client'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { AlertCircle, BookOpen, ShieldCheck } from 'lucide-react'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useTranslation } from '@/lib/hooks/use-translation'
import { GoogleSignInButton } from '@/components/auth/GoogleSignInButton'
import { ThemeToggle } from '@/components/common/ThemeToggle'

function LoginFormContent() {
  const { t } = useTranslation()
  const { hasHydrated, isAuthenticated, setAuthSession } = useAuthStore()
  const [isCheckingAuth, setIsCheckingAuth] = useState(true)
  const [configInfo, setConfigInfo] = useState<{ apiUrl: string; version: string } | null>(null)
  const [authError, setAuthError] = useState<string | null>(null)
  const router = useRouter()
  const searchParams = useSearchParams()

  // Load config info for version display
  useEffect(() => {
    getConfig()
      .then((cfg) => {
        setConfigInfo({
          apiUrl: cfg.apiUrl,
          version: cfg.version,
        })
      })
      .catch((err) => {
        console.error('Failed to load config:', err)
      })
  }, [])

  // Check URL query parameters for error flags
  useEffect(() => {
    const errorParam = searchParams.get('error')
    if (errorParam) {
      setAuthError(t('auth.callbackError'))
    }
  }, [searchParams, t])

  // Check existing Supabase session on mount
  useEffect(() => {
    if (!hasHydrated) return

    const checkExistingSession = async () => {
      try {
        if (!isSupabaseConfigured()) {
          setAuthError(t('auth.supabaseNotConfigured'))
          setIsCheckingAuth(false)
          return
        }

        const { data: { session } } = await supabase.auth.getSession()
        if (session?.access_token) {
          setAuthSession(session.access_token)
          const redirectPath = sessionStorage.getItem('redirectAfterLogin') || '/notebooks'
          sessionStorage.removeItem('redirectAfterLogin')
          router.replace(redirectPath)
          return
        }

        // If Supabase has no active session, ensure store is cleared
        if (isAuthenticated) {
          useAuthStore.setState({ isAuthenticated: false, token: null })
        }
      } catch (error) {
        console.error('Error during initial session check:', error)
      } finally {
        setIsCheckingAuth(false)
      }
    }

    void checkExistingSession()
  }, [hasHydrated, isAuthenticated, router, setAuthSession, t])

  // Show loading spinner while determining auth state
  if (!hasHydrated || isCheckingAuth) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <LoadingSpinner className="h-8 w-8 text-fern" />
      </div>
    )
  }

  return (
    <div className="min-h-screen relative flex flex-col justify-between bg-background selection:bg-fern-tint selection:text-fern-deep">
      {/* Top utility bar */}
      <header className="w-full max-w-6xl mx-auto px-6 py-4 flex items-center justify-between z-10">
        <div className="flex items-center gap-2.5">
          <div className="size-8 rounded-lg bg-fern-tint border border-fern/20 flex items-center justify-center text-fern shadow-xs">
            <BookOpen className="size-4" />
          </div>
          <span className="font-semibold text-sm tracking-tight text-foreground">
            {t('auth.loginTitle')}
          </span>
        </div>

        <div className="flex items-center border border-border/80 bg-card/60 backdrop-blur-xs rounded-lg p-0.5 shadow-xs">
          <ThemeToggle iconOnly />
        </div>
      </header>

      {/* Main centered card */}
      <main className="flex-1 flex items-center justify-center p-4 z-10">
        <div className="w-full max-w-[400px]">
          <Card className="border border-border/90 bg-card shadow-xs rounded-xl p-2 sm:p-4">
            <CardHeader className="text-center pb-6 pt-2">
              <div className="size-14 rounded-2xl bg-fern-tint border border-fern/25 flex items-center justify-center mx-auto mb-4 text-fern shadow-xs">
                <BookOpen className="size-7" />
              </div>
              <CardTitle className="text-2xl font-bold tracking-tight text-foreground">
                {t('auth.loginTitle')}
              </CardTitle>
              <CardDescription className="text-muted-foreground text-sm mt-1 px-2">
                {t('auth.welcomeSubtitle')}
              </CardDescription>
            </CardHeader>

            <CardContent className="space-y-5">
              {authError && (
                <div className="flex items-start gap-2.5 p-3 rounded-lg bg-destructive-tint/20 border border-destructive/20 text-destructive text-xs leading-relaxed">
                  <AlertCircle className="size-4 shrink-0 mt-0.5" />
                  <div className="flex-1">{authError}</div>
                </div>
              )}

              <GoogleSignInButton />

              <div className="pt-2 flex items-center justify-center gap-1.5 text-xs text-muted-foreground">
                <ShieldCheck className="size-3.5 text-sage" />
                <span>{t('auth.secureAuthNote')}</span>
              </div>
            </CardContent>
          </Card>
        </div>
      </main>

      {/* Footer */}
      <footer className="w-full py-4 text-center text-xs text-muted-foreground/60 z-10">
        {configInfo && (
          <div className="space-y-0.5">
            <div>StudyBook v{configInfo.version}</div>
          </div>
        )}
      </footer>
    </div>
  )
}

export function LoginForm() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-background">
          <LoadingSpinner className="h-8 w-8 text-fern" />
        </div>
      }
    >
      <LoginFormContent />
    </Suspense>
  )
}