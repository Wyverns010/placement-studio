import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Nav from './Nav'

const REPO = 'https://github.com/Wyverns010/placement-studio'

describe('Nav', () => {
  it('links GitHub, Prompts and Evals to the repo in a new tab, and nothing dead', () => {
    render(<Nav onHome={() => {}} />)
    const cases: [string, string][] = [
      ['GitHub', REPO],
      ['Prompts', `${REPO}/tree/main/prompts`],
      ['Evals', `${REPO}/tree/main/evals`],
    ]
    for (const [name, href] of cases) {
      const a = screen.getByRole('link', { name })
      expect(a).toHaveAttribute('href', href)
      expect(a).toHaveAttribute('target', '_blank')
      expect(a.getAttribute('rel')).toContain('noopener')
    }
    for (const dead of ['How it works', 'Publishers', 'Personas']) {
      expect(screen.queryByText(dead)).toBeNull()
    }
  })
})
