import {
  ChartBar,
  Database,
  Gear,
  House,
  ListChecks,
  MapTrifold,
  Question,
  VideoCamera,
} from "@phosphor-icons/react";

const navItems = [
  { id: "overview", label: "Overview", icon: House },
  { id: "map", label: "지도", icon: MapTrifold },
  { id: "events", label: "이벤트", icon: ListChecks },
  { id: "video", label: "영상", icon: VideoCamera },
  { id: "report", label: "리포트", icon: ChartBar },
  { id: "rosbag", label: "ROS Bag 기록", icon: Database },
];

export default function Sidebar({ active, onNavigate, pendingEvents }) {
  return (
    <aside className="sidebar" aria-label="주 메뉴">
      <div className="sidebar-main">
        <nav className="nav-primary">
          {navItems.map(({ id, label, icon: Icon, badge }) => (
            <button key={id} type="button" className={`nav-item ${active === id ? "active" : ""}`} onClick={() => onNavigate(id)}>
              <Icon size={20} weight={active === id ? "fill" : "regular"} />
              <span>{label}</span>
              {(id === "events" ? pendingEvents : badge) ? <span className="nav-badge">{id === "events" ? pendingEvents : badge}</span> : null}
            </button>
          ))}
        </nav>
      </div>
      <nav className="nav-secondary" aria-label="보조 메뉴">
        <button type="button" className={`nav-item ${active === "settings" ? "active" : ""}`} onClick={() => onNavigate("settings")}>
          <Gear size={20} weight={active === "settings" ? "fill" : "regular"} />
          <span>설정</span>
        </button>
        <button type="button" className={`nav-item ${active === "help" ? "active" : ""}`} onClick={() => onNavigate("help")}>
          <Question size={20} weight={active === "help" ? "fill" : "regular"} />
          <span>도움말</span>
        </button>
        <div className="sidebar-version">
          <span>HazardGuard Console</span>
          <small>Prototype v0.1.0</small>
        </div>
      </nav>
    </aside>
  );
}
