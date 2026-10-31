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
      partial={{}}
      onTextChange={noop}
      onBudgetChange={noop}
      onRun={noop}
      onPickSample={noop}
    />,
  )
}

describe('Landing', () => {
  it('caps the brief at 1500 characters and shows a counter', () => {
    setup('Dog food')
    expect(screen.getByLabelText('Describe your brand')).toHaveAttribute('maxLength', '1500')
    expect(screen.getByText('8 / 1500')).toBeInTheDocument()
  })
})
