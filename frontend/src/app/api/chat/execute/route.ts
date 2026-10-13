import type { NextRequest } from 'next/server'

const INTERNAL_API_URL = process.env.INTERNAL_API_URL || 'http://localhost:5055'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
export const maxDuration = 300

export async function POST(req: NextRequest) {
  const body = await req.text()
  const auth = req.headers.get('authorization')

  try {
    const upstream = await fetch(`${INTERNAL_API_URL}/api/chat/execute`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(auth ? { Authorization: auth } : {}),
      },
      body,
      cache: 'no-store',
    })

    const data = await upstream.text()
    return new Response(data, {
      status: upstream.status,
      headers: {
        'Content-Type': upstream.headers.get('content-type') ?? 'application/json',
      },
    })
  } catch (error: any) {
    console.error('Error proxying /api/chat/execute:', error)
    return new Response(
      JSON.stringify({ detail: error?.message || 'Error communicating with chat backend' }),
      {
        status: 502,
        headers: { 'Content-Type': 'application/json' },
      }
    )
  }
}
