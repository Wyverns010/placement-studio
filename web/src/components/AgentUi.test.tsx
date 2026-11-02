import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AgentNotes, AgentSteer, AgentTicker, AgentWorking } from './AgentUi'

describe('AgentNotes', () => {
  it('lists the notes', () => {
    render(<AgentNotes notes={['Left out Pawline (pet) because of your note.']} />)
    expect(within(screen.getByTestId('agent-notes')).getByText('Left out Pawline (pet) because of your note.')).toBeInTheDocument()
  })

  it('renders nothing without notes', () => {
    const { container } = render(<AgentNotes notes={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('AgentTicker', () => {
  it('shows the latest tool call', () => {
    render(
      <AgentTicker
        trace={[
          { agent: 'strategist', tool: 'decide', args_summary: '{}', result_summary: 'proceed', ms: 0 },
          { agent: 'strategist', tool: 'rank_publishers', args_summary: '{}', result_summary: '[]', ms: 3 },
        ]}
      />,
    )
    expect(screen.getByTestId('agent-ticker')).toHaveTextContent('Agent: rank_publishers …')
  })
})

describe('AgentSteer', () => {
  it('shows a counter, applies the trimmed text, and blocks a blank apply', async () => {
    const user = userEvent.setup()
    const onApply = vi.fn()
    let value = ''
    const { rerender } = render(<AgentSteer placeholder="Skip pet stores" value={value} onChange={(v) => (value = v)} onApply={onApply} />)
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled()
    expect(screen.getByPlaceholderText(/skip pet stores/i)).toBeInTheDocument()
    expect(screen.getByTestId('steer-count')).toHaveTextContent('0/300')
    rerender(<AgentSteer placeholder="Skip pet stores" value="  no pets " onChange={() => {}} onApply={onApply} />)
    expect(screen.getByTestId('steer-count')).toHaveTextContent('10/300')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onApply).toHaveBeenCalledWith('no pets')
  })

  it('caps the input at 300 characters', () => {
    render(<AgentSteer placeholder="x" value="" onChange={() => {}} onApply={() => {}} />)
    expect(screen.getByLabelText('Tell the agent')).toHaveAttribute('maxlength', '300')
  })
})

describe('AgentWorking', () => {
  it('says what the team is doing, step by step, without a timer', () => {
    vi.useFakeTimers()
    try {
      render(<AgentWorking personas={['The Pet Parent', 'The Busy Parent']} publishers={['Pawline']} />)
      const s = screen.getByTestId('agent-working')
      expect(s).toHaveAttribute('role', 'status')
      expect(s).toHaveTextContent('Reading what The Pet Parent cares about…')
      act(() => vi.advanceTimersByTime(2200))
      expect(s).toHaveTextContent('Writing for The Pet Parent on Pawline…')
      act(() => vi.advanceTimersByTime(60_000))
      expect(s).toHaveTextContent('Final checks on the ads…') // holds on the last step
      expect(s.textContent).not.toMatch(/\d+ s/)
    } finally {
      vi.useRealTimers()
    }
  })
})
