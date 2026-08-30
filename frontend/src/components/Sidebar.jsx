import React from 'react'

export default function Sidebar({ activeNav, setActiveNav, stage, onLogout, username }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-inner">
        <div style={{ display: 'flex', justifyContent: 'center', padding: '12px 0' }}>
          <div className="avatar">AP</div>
        </div>

        <nav className="nav">
          {stage === 'app' && (
            <>
              <button className={`nav-item ${activeNav === 'dashboard' ? 'active' : ''}`} onClick={() => setActiveNav('dashboard')}>🏠 Dashboard</button>
              <button className={`nav-item ${activeNav === 'profile' ? 'active' : ''}`} onClick={() => setActiveNav('profile')}>👤 Profile</button>
            </>
          )}

          {stage === 'plans' && username && (
            <div style={{ padding: '8px 14px', color: 'var(--text-muted)', fontSize: '0.9rem' }}>
              Signed in as <strong>{username}</strong>
            </div>
          )}
        </nav>

        {(stage === 'app' || stage === 'plans') && (
          <div className="sidebar-footer">
            <button className="small-btn" onClick={onLogout}>Sign Out</button>
          </div>
        )}
      </div>
    </aside>
  )
}
