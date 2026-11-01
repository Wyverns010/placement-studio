import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AgentPanel, AgentSteer, AgentTicker, AgentWorking } from './AgentUi'

const meta = {
  mode: 'agent' as const,
  agent_notes: ['Left out Pawline (pet) because of your note.'],
  agent_trace: [
    { agent: 'strategist', tool: 'decide', args_summary: '{}', result_summary: 'proceed: build the campaign', ms: 0 },
    { agent: 'strategist', tool: 'rank_publishers', args_summary: '{"exclude_ids":["pub_007"]}', result_summary: '[{"id":"pub_020"', ms: 3 },
  ],
}

describe('AgentPanel', () => {
  it('is collapsed by default, with the mode badge visible', async () => {
    render(<AgentPanel meta={meta} />)
    const toggle = screen.getByRole('button', { name: /what the agent did/i })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByTestId('mode-badge')).toHaveTextContent('Agent')
    expect(screen.queryByTestId('agent-notes')).not.toBeInTheDocument()
  })

  it('shows notes first, then the trace timeline when opened', async () => {
    const user = userEvent.setup()
    render(<AgentPanel meta={meta} />)
    await user.click(screen.getByRole('button', { name: /what the agent did/i }))
    const notes = screen.getByTestId('agent-notes')
    const timeline = screen.getByTestId('agent-timeline')
    expect(within(notes).getByText('Left out Pawline (pet) because of your note.')).toBeInTheDocument()
    expect(notes.compareDocumentPosition(timeline) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    const items = within(timeline).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[1]).toHaveTextContent('strategist')
    expect(items[1]).toHaveTextContent('rank_publishers')
    expect(items[1]).toHaveTextContent('3 ms')
    expect(items[1]).toHaveTextContent('exclude_ids')
  })

  it.each([
    ['agent', 'Agent'],
    ['code', 'Code'],
    ['fallback', 'Fallback (agent unavailable)'],
  ] as const)('badge for mode %s', (mode, label) => {
    render(<AgentPanel meta={{ mode }} />)
    expect(screen.getByTestId('mode-badge')).toHaveTextContent(label)
  })

  it('renders nothing without any agent data', () => {
    const { container } = render(<AgentPanel meta={{}} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('AgentTicker', () => {
  it('shows the latest tool call', () => {
    render(<AgentTicker trace={meta.agent_trace} />)
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
