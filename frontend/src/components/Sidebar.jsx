import React from 'react'

export default function Sidebar({ user, onLogout }) {
  const username = user?.username || 'Guest'
  const initials = username.slice(0, 2).toUpperCase()

  return (
    <aside className="sidebar">
      <div className="sidebar-inner">
        <div className="avatar" aria-hidden="true">{initials}</div>
        <p className="profile-name">{username}</p>
        {user ? (
          <p className="profile-status">Signed in</p>
        ) : (
          <p className="profile-status profile-status--muted">Not signed in</p>
        )}

        {user && (
          <button className="btn btn-secondary btn-sm btn-block" onClick={onLogout}>
            Log out
          </button>
        )}
      </div>
    </aside>
  )
}
