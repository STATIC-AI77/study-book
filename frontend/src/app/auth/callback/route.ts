import { NextResponse, type NextRequest } from 'next/server'
import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'

function getOrigin(request: NextRequest): string {
  // Check x-forwarded-host first (for reverse proxies like lightning.ai)
  const forwardedHost = request.headers.get('x-forwarded-host') || request.headers.get('host')
  const forwardedProto = request.headers.get('x-forwarded-proto') || (request.url.startsWith('https') ? 'https' : 'http')

  if (forwardedHost && !forwardedHost.startsWith('0.0.0.0')) {
    return `${forwardedProto}://${forwardedHost}`
  }

  const origin = request.nextUrl.origin
  if (origin && !origin.includes('0.0.0.0')) {
    return origin
  }

  if (forwardedHost) {
    return `${forwardedProto}://${forwardedHost.replace('0.0.0.0', 'localhost')}`
  }

  return 'http://localhost:3000'
}

export async function GET(request: NextRequest) {
  const requestUrl = new URL(request.url)
  const code = requestUrl.searchParams.get('code')
  const origin = getOrigin(request)
  const next = requestUrl.searchParams.get('next') || '/notebooks'

  if (code) {
    const cookieStore = await cookies()
    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL || '',
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || '',
      {
        cookies: {
          getAll() {
            return cookieStore.getAll()
          },
          setAll(cookiesToSet) {
            try {
              cookiesToSet.forEach(({ name, value, options }) =>
                cookieStore.set(name, value, options)
              )
            } catch {
              // The setAll method was called from a Server Component / Route Handler
            }
          },
        },
      }
    )

    const { error } = await supabase.auth.exchangeCodeForSession(code)
    if (!error) {
      return NextResponse.redirect(`${origin}${next}`)
    }
    console.error('Error exchanging OAuth code for session:', error)
  }

  return NextResponse.redirect(`${origin}/login?error=auth_callback_failed`)
}
