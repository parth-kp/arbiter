import { NavLink, Route, Routes } from 'react-router-dom'
import Runs from './pages/Runs'
import RunDetail from './pages/RunDetail'
import Compare from './pages/Compare'
import Scenario from './pages/Scenario'
import Failures from './pages/Failures'
import Trace from './pages/Trace'
import Label from './pages/Label'
import Calibration from './pages/Calibration'
import Approvals from './pages/Approvals'

export default function App() {
  return (
    <>
      <header className="topbar">
        <NavLink to="/" className="wordmark" end>
          <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="6" fill="currentColor" />
            <path d="M8 22 16 8l8 14M11 18h10" stroke="var(--paper)" strokeWidth="2.4" fill="none" />
          </svg>
          Arbiter
        </NavLink>
        <nav>
          <NavLink to="/" end>Runs</NavLink>
          <NavLink to="/approvals">Approvals</NavLink>
          <NavLink to="/label">Labelling</NavLink>
          <NavLink to="/calibration">Calibration</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Runs />} />
          <Route path="/runs/:id" element={<RunDetail />} />
          <Route path="/runs/:id/failures" element={<Failures />} />
          <Route path="/runs/:id/scenarios/:sid" element={<Scenario />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/traces/:id" element={<Trace />} />
          <Route path="/label" element={<Label />} />
          <Route path="/calibration" element={<Calibration />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="*" element={<p className="empty">Page not found.</p>} />
        </Routes>
      </main>
    </>
  )
}
