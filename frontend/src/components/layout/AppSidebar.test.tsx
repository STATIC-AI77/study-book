/* eslint-disable @typescript-eslint/no-explicit-any */
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { usePathname } from 'next/navigation'
import { AppSidebar } from './AppSidebar'
import { useSidebarStore } from '@/lib/stores/sidebar-store'

// Mock Tooltip components to avoid Radix UI async issues in tests
vi.mock('@/components/ui/tooltip', () => ({
  TooltipProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

describe('AppSidebar', () => {
  afterEach(() => {
    vi.mocked(usePathname).mockReturnValue('')
  })

  it('highlights Models on the Models page', () => {
    vi.mocked(usePathname).mockReturnValue('/settings/models')

    const { container } = render(<AppSidebar />)

    const modelsButton = container.querySelector('a[href="/settings/models"] button')
    const transformationsButton = container.querySelector('a[href="/transformations"] button')

    expect(modelsButton?.className).toContain('font-semibold')
    expect(transformationsButton?.className).toContain('font-medium')
    expect(transformationsButton?.className).not.toContain('font-semibold')
  })

  it('renders correctly when expanded', () => {
    render(<AppSidebar />)

    // With mocked t() returning keys, check for translation key strings
    expect(screen.getByText('common.appName')).toBeDefined()
    expect(screen.getByText('navigation.sources')).toBeDefined()
    expect(screen.getByText('navigation.notebooks')).toBeDefined()
  })

  it('renders footer actions and sign out button', () => {
    render(<AppSidebar />)

    const themeButton = screen.getByText('common.theme').closest('button')
    const signOutButton = screen.getByRole('button', { name: 'common.signOut' })

    expect(themeButton).toBeDefined()
    expect(signOutButton).toBeDefined()
    expect(themeButton?.querySelector(':scope > span.relative.size-4')).not.toBeNull()
  })

  it('toggles collapse state when clicking handle', () => {
    const toggleCollapse = vi.fn()
    vi.mocked(useSidebarStore).mockReturnValue({
      isCollapsed: false,
      toggleCollapse,
    } as any)

    render(<AppSidebar />)

    fireEvent.click(screen.getByTestId('sidebar-toggle'))

    expect(toggleCollapse).toHaveBeenCalled()
  })

  it('shows collapsed view when isCollapsed is true', () => {
    vi.mocked(useSidebarStore).mockReturnValue({
      isCollapsed: true,
      toggleCollapse: vi.fn(),
    } as any)

    render(<AppSidebar />)

    // In collapsed mode, app name shouldn't be visible (as text)
    expect(screen.queryByText('common.appName')).toBeNull()
  })
})
