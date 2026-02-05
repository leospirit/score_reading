import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Navigation from './components/Navigation';
import Dashboard from './pages/Dashboard';
import HistoryPage from './pages/History';
import ReportBuilder from './pages/ReportBuilder';

function App() {
  return (
    <Router>
      <div className="bg-background min-h-screen text-text font-body selection:bg-primary selection:text-background">
        <Navigation />

        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/report-builder" element={<ReportBuilder />} />
        </Routes>

        {/* Simple Footer */}
        <footer className="border-t border-white/10 py-12 bg-black/40 mt-auto">
          <div className="max-w-7xl mx-auto px-4 text-center text-gray-500 text-sm">
            <p>&copy; 2026 SpeechMaster. All rights reserved.</p>
          </div>
        </footer>
      </div>
    </Router>
  );
}

export default App;
