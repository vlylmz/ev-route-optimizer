import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { VehicleSelect } from './VehicleSelect'
import type { VehicleSummary } from '../services/schemas'

const vehicles: VehicleSummary[] = [
  {
    id: 'tesla_model_y_rwd',
    name: 'Tesla Model Y RWD',
    make: 'Tesla',
    model: 'Model Y',
    variant: 'RWD',
    year: 2024,
    body_type: 'SUV',
    usable_battery_kwh: 57.5,
    ideal_consumption_wh_km: 157,
    wltp_range_km: 455,
    max_dc_charge_kw: 250,
  },
]

describe('VehicleSelect', () => {
  it('renders options from vehicle list', () => {
    render(
      <VehicleSelect vehicles={vehicles} value="tesla_model_y_rwd" onChange={() => {}} />,
    )
    expect(screen.getByLabelText('Araç')).toBeInTheDocument()
    expect(
      screen.getByText(/Tesla Model Y RWD · 57.5 kWh · 250 kW DC/),
    ).toBeInTheDocument()
  })

  it('shows loading state', () => {
    render(<VehicleSelect vehicles={[]} value="" onChange={() => {}} isLoading />)
    expect(screen.getByText('Yükleniyor…')).toBeInTheDocument()
  })

  it('calls onChange when selection changes', () => {
    const onChange = vi.fn()
    const multi: VehicleSummary[] = [
      vehicles[0],
      { ...vehicles[0], id: 'vw_id4', name: 'VW ID.4' },
    ]
    render(
      <VehicleSelect vehicles={multi} value="tesla_model_y_rwd" onChange={onChange} />,
    )
    fireEvent.change(screen.getByLabelText('Araç'), { target: { value: 'vw_id4' } })
    expect(onChange).toHaveBeenCalledWith('vw_id4')
  })
})
