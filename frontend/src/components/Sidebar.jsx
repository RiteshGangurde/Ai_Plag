import React from 'react'

export default function Sidebar({ activeNav, setActiveNav }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-inner">
        <div style={{ display: 'flex', justifyContent: 'center', padding: '12px 0' }}>
          <div className="avatar">AP</div>
        </div>

        <nav className="nav">
          <button className={`nav-item ${activeNav==='dashboard'?'active':''}`} onClick={() => setActiveNav('dashboard')}>🏠 Dashboard</button>
          <button className={`nav-item ${activeNav==='upload'?'active':''}`} onClick={() => setActiveNav('upload')}>📤 Upload</button>
          <button className={`nav-item ${activeNav==='reports'?'active':''}`} onClick={() => setActiveNav('reports')}>📑 Reports</button>
          <button className={`nav-item ${activeNav==='profile'?'active':''}`} onClick={() => setActiveNav('profile')}>👤 Profile</button>
          <button className={`nav-item ${activeNav==='login'?'active':''}`} onClick={() => setActiveNav('login')}>🔐 Sign In / Sign Up</button>
          <button className={`nav-item ${activeNav==='settings'?'active':''}`} onClick={() => setActiveNav('settings')}>⚙️ Settings</button>
          <button className={`nav-item ${activeNav==='help'?'active':''}`} onClick={() => setActiveNav('help')}>❓ Help</button>
        </nav>

        <div className="sidebar-footer">
          <button className="small-btn">Settings</button>
          <button className="small-btn">Logout</button>
        </div>
      </div>
    </aside>
  )
}
