export interface UserProfile {
  email?: string | null
  avatarUrl?: string | null
  name?: string | null
}

export interface AuthState {
  isAuthenticated: boolean
  token: string | null
  user: UserProfile | null
  isLoading: boolean
  error: string | null
}

export interface LoginCredentials {
  password: string
}