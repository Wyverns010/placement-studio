import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Landing from './Landing'

const noop = () => {}

function setup(text: string) {
  render(
    <Landing
      samples={[]}
      text={text}
      budget=""
      running={false}
      error={null}
      lastResult={null}
      onTextChange={noop}
      onBudgetChange={noop}
      onRun={noop}
      onPickSample={noop}
    />,
  )
}

describe('Landing', () => {
  it('does not cap the brief length', () => {
    setup('Dog food')
    expect(screen.getByLabelText('Describe your brand')).not.toHaveAttribute('maxLength')
    expect(screen.queryByText(/\/ 1500/)).not.toBeInTheDocument()
  })
})
