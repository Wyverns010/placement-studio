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
  it('says what the team is doing and counts the seconds', () => {
    vi.useFakeTimers()
    try {
      render(<AgentWorking />)
      const s = screen.getByTestId('agent-working')
      expect(s).toHaveAttribute('role', 'status')
      expect(s).toHaveTextContent('The copywriter is drafting, the critic is reviewing… 0 s')
      act(() => vi.advanceTimersByTime(12_000))
      expect(s).toHaveTextContent('… 12 s')
    } finally {
      vi.useRealTimers()
    }
  })
})
