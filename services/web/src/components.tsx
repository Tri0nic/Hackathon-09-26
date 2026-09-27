import type { Alert, Channel, RiskLevel } from "./types";
import { alertKindLabel, levelName, picketPosition, riskLabel, splitPickets } from "./domain";

export function RiskBadge({ level }: { level: RiskLevel }) {
  return <span className={`risk-badge level-${level}`}><i />{levelName[level]} · {riskLabel(level)}</span>;
}

export function KindBadge({ alert }: { alert: Alert }) {
  return <span className={`kind-badge ${alert.kind}`}>{alert.kind === "malfunction" ? "⌁" : "△"} {alertKindLabel(alert.kind)}</span>;
}

export function PageTitle({ title, subtitle, children }: { title: string; subtitle: string; children?: React.ReactNode }) {
  return <header className="page-title"><div><h1>{title}</h1><p>{subtitle}</p></div><div className="page-actions">{children}</div></header>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function ProbabilityChart({ alert, compact = false }: { alert: Alert; compact?: boolean }) {
  const points = [alert.pNow, alert.p6h, alert.p12h, alert.p24h];
  const coords = points.map((value, index) => `${30 + index * 100},${116 - value * 90}`).join(" ");
  return <div className={`probability-chart ${compact ? "compact" : ""}`}>
    <svg viewBox="0 0 360 145" role="img" aria-label="Динамика вероятности по горизонтам">
      {[25, 70, 115].map((y) => <line key={y} x1="30" y1={y} x2="330" y2={y} className="grid-line" />)}
      <polyline points={coords} className={`risk-line level-${alert.level}`} />
      {points.map((value, index) => <g key={index}>
        <circle cx={30 + index * 100} cy={116 - value * 90} r="5" className={`point level-${alert.level}`} />
        <text x={30 + index * 100} y="137" textAnchor="middle">{["Сейчас", "6 ч", "12 ч", "24 ч"][index]}</text>
        <text x={30 + index * 100} y={106 - value * 90} textAnchor="middle" className="value">{Math.round(value * 100)}%</text>
      </g>)}
    </svg>
  </div>;
}

function markerColor(channel: Channel) {
  return channel.state === "danger" ? "#d9363e" : channel.state === "warning" ? "#d99a16" : channel.state === "malfunction" ? "#6654d9" : "#2f8f61";
}

export function PicketMap({ channels, alert }: { channels: Channel[]; alert?: Alert }) {
  const { located, withoutPicket } = splitPickets(channels);
  const keys = located.map((channel) => channel.picketSortKey!);
  const x = (value: number) => picketPosition(value, keys);
  return <div className="map-wrap">
    <div className="map-scroll">
      <svg className="picket-map" viewBox="0 0 780 210" role="img" aria-label="Линейная схема пикетов">
        <line x1="50" y1="104" x2="730" y2="104" className="collector-line" />
        {alert?.picketFrom != null && alert?.picketTo != null && <line x1={x(alert.picketFrom)} y1="104" x2={x(alert.picketTo)} y2="104" className={`danger-range level-${alert.level}`} />}
        {located.map((channel, index) => {
          const cx = x(channel.picketSortKey!);
          const top = index % 2 === 0;
          return <g key={channel.id} className="sensor-marker">
            <line x1={cx} y1="104" x2={cx} y2={top ? 62 : 146} />
            <circle cx={cx} cy={top ? 52 : 156} r="10" fill={markerColor(channel)} />
            <text x={cx} y={top ? 28 : 188} textAnchor="middle">ПК {channel.picketRaw}</text>
            <title>{`${channel.name}: ${channel.value ?? "нет значения"}`}</title>
          </g>;
        })}
      </svg>
    </div>
    <div className="legend"><span><i className="dot danger" /> Тревога</span><span><i className="dot warning" /> Внимание</span><span><i className="dot normal" /> Норма</span><span><i className="dot malfunction" /> Неисправность</span></div>
    <section className="unlocated"><h3>Каналы без распознанного пикета <span>{withoutPicket.length}</span></h3>
      {withoutPicket.length ? withoutPicket.map((channel) => <div className="channel-row" key={channel.id}><div><b>{channel.name}</b><small>{channel.sensorType}</small></div><span className={`sensor-state ${channel.state}`}>{channel.value}</span></div>) : <p>Все каналы привязаны к пикетам.</p>}
    </section>
  </div>;
}
