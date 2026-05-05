import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ProfileCard } from './ProfileCard'
import type { ProfileCard as ProfileCardType } from '../services/schemas'

const baseCard: ProfileCardType = {
  key: 'balanced',
  label: 'Dengeli',
  feasible: true,
  total_energy_kwh: 24.12,
  total_trip_minutes: 185.4,
  charging_minutes: 20,
  stop_count: 1,
  final_soc_pct: 25,
  used_ml: false,
  model_version: null,
  recommended_stops: [],
  total_cost_try: 0,
  raw: {},
}

describe('ProfileCard', () => {
  it('renders summary stats', () => {
    render(<ProfileCard card={baseCard} />)
    expect(screen.getByText('Dengeli')).toBeInTheDocument()
    expect(screen.getByText('24.1 kWh')).toBeInTheDocument()
    expect(screen.getByText('185 dk')).toBeInTheDocument()
    expect(screen.getByText('Formül')).toBeInTheDocument()
  })

  it('shows "Önerilen" badge when recommended', () => {
    render(<ProfileCard card={baseCard} recommended />)
    expect(screen.getByText('Önerilen')).toBeInTheDocument()
  })

  it('renders ML source when used_ml', () => {
    render(
      <ProfileCard
        card={{ ...baseCard, used_ml: true, model_version: 'lgbm_v1' }}
      />,
    )
    expect(screen.getByText(/ML/)).toBeInTheDocument()
    expect(screen.getByText(/lgbm_v1/)).toBeInTheDocument()
  })

  it('shows dash for missing values', () => {
    render(
      <ProfileCard
        card={{
          ...baseCard,
          total_energy_kwh: null,
          charging_minutes: null,
          stop_count: null,
          final_soc_pct: null,
        }}
      />,
    )
    const dashes = screen.getAllByText('—')
    expect(dashes.length).toBeGreaterThanOrEqual(3)
  })

  it('marks infeasible profile', () => {
    render(<ProfileCard card={{ ...baseCard, feasible: false }} />)
    expect(screen.getByText('Uygun değil')).toBeInTheDocument()
  })
})
