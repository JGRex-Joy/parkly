import { Navigate, Route, Routes } from 'react-router-dom'
import { ParkingProvider } from './store/ParkingContext.jsx'
import Layout from './components/Layout.jsx'
import TwinPage from './pages/TwinPage.jsx'
import CrmPage from './pages/CrmPage.jsx'

export default function App() {
  return (
    <ParkingProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/twin" replace />} />
          <Route path="/twin" element={<TwinPage />} />
          <Route path="/crm" element={<CrmPage />} />
          <Route path="*" element={<Navigate to="/twin" replace />} />
        </Route>
      </Routes>
    </ParkingProvider>
  )
}
