import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { alertKindLabel, formatDate, requestStatusName, riskLabel } from "./domain";
import { Empty, KindBadge, PageTitle, PicketMap, ProbabilityChart, RiskBadge } from "./components";
import type { Alert, AppData, RequestStatus, RiskObject } from "./types";

const nav = [
  ["/", "Обзор", "▦"], ["/objects", "Объекты", "⌘"], ["/alerts", "Предупреждения", "△"],
  ["/requests", "Заявки", "▤"], ["/analytics", "Аналитика", "⌁"], ["/sms", "Журнал SMS", "✉"]
] as const;

const roles = [
  { value: "technician", name: "Техник", initials: "ТХ", scope: "Закреплённые объекты" },
  { value: "district_dispatcher", name: "Диспетчер района", initials: "ДР", scope: "Объекты района" },
  { value: "ods_dispatcher", name: "Диспетчер ОДС", initials: "ДО", scope: "Все объекты" },
  { value: "response_team", name: "Группа реагирования", initials: "ГР", scope: "Критические события BLACK" }
] as const;

type UserRole = typeof roles[number]["value"];

function savedRole(): UserRole {
  if (typeof window === "undefined") return "ods_dispatcher";
  try {
    const value = window.localStorage.getItem("fire-risk-role");
    return roles.some((role) => role.value === value) ? value as UserRole : "ods_dispatcher";
  } catch {
    return "ods_dispatcher";
  }
}

function go(path: string, setPath: (path: string) => void) {
  if (typeof window !== "undefined") window.history.pushState({}, "", path);
  setPath(path);
  if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" });
}

function Link({ to, setPath, children, className }: { to: string; setPath: (value: string) => void; children: React.ReactNode; className?: string }) {
  return <a href={to} className={className} onClick={(event) => { event.preventDefault(); go(to, setPath); }}>{children}</a>;
}

function Dashboard({ data, setPath }: { data: AppData; setPath: (path: string) => void }) {
  const critical = data.alerts.filter((alert) => alert.level === "black" || alert.level === "red").length;
  return <>
    <PageTitle title="Мониторинг рисков" subtitle="Прогноз состояния инженерной инфраструктуры на 24 часа">
      <button className="secondary">Обновить данные</button>
    </PageTitle>
    <div className="filters"><label>Горизонт <select><option>24 часа</option></select></label><label>Округ <select><option>Все округа</option></select></label><label>Тип риска <select><option>Все типы</option></select></label></div>
    <div className="kpi-grid">
      <article className="kpi danger"><span>Критические риски</span><strong>{critical}</strong><small>требуют решения</small></article>
      <article className="kpi warning"><span>Активные предупреждения</span><strong>{data.alerts.length}</strong><small>в текущих эпизодах</small></article>
      <article className="kpi info"><span>Объекты под контролем</span><strong>{data.objects.length}</strong><small>{data.objects.length - critical} без критических отклонений</small></article>
      <article className="kpi success"><span>Открытые заявки</span><strong>{data.requests.filter((request) => !["completed", "rejected"].includes(request.status)).length}</strong><small>профилактика и проверка</small></article>
    </div>
    <div className="dashboard-grid">
      <section className="panel wide"><div className="panel-head"><div><h2>Объекты внимания</h2><p>По максимальной вероятности активного риска</p></div><Link to="/objects" setPath={setPath}>Все объекты →</Link></div>
        <div className="table-wrap"><table><thead><tr><th>Объект</th><th>Округ</th><th>Вероятность</th><th>Уровень</th></tr></thead><tbody>{data.objects.map((object) => <tr key={object.id} className="clickable" onClick={() => go(`/objects/${object.id}`, setPath)}><td><b>{object.name}</b><small>{object.channelCount} каналов</small></td><td>{object.district}</td><td><strong>{Math.round(object.probability * 100)}%</strong></td><td><RiskBadge level={object.level} /></td></tr>)}</tbody></table></div>
      </section>
      <section className="panel"><div className="panel-head"><div><h2>Динамика главного риска</h2><p>{data.alerts[0]?.objectName}</p></div></div>{data.alerts[0] && <ProbabilityChart alert={data.alerts[0]} />}</section>
    </div>
    <section className="panel"><div className="panel-head"><div><h2>Последние предупреждения</h2><p>Расчёты модели и технические события</p></div><Link to="/alerts" setPath={setPath}>Открыть журнал →</Link></div><AlertTable alerts={data.alerts} setPath={setPath} /></section>
  </>;
}

function AlertTable({ alerts, setPath }: { alerts: Alert[]; setPath: (path: string) => void }) {
  return <div className="table-wrap"><table><thead><tr><th>Время</th><th>Объект и тип</th><th>Вероятность</th><th>Уровень и горизонт</th><th>Решение</th></tr></thead><tbody>{alerts.map((alert) => <tr key={alert.id} className="clickable" onClick={() => go(`/alerts/${alert.id}`, setPath)}><td>{formatDate(alert.calculatedAt)}</td><td><b>{alert.objectName}</b><small>{alertKindLabel(alert.kind)}</small></td><td><strong>{Math.round(alert.probability * 100)}%</strong></td><td><RiskBadge level={alert.level} /></td><td>{alert.decisions[0]?.decision ?? <span className="muted">Ожидает решения</span>}</td></tr>)}</tbody></table></div>;
}

function ObjectsPage({ data, path, setPath }: { data: AppData; path: string; setPath: (path: string) => void }) {
  const id = path.split("/")[2];
  const object = data.objects.find((item) => item.id === id);
  if (!object) return <><PageTitle title="Объекты" subtitle="Инфраструктурные объекты и каналы мониторинга" /><div className="object-cards">{data.objects.map((item) => <ObjectCard key={item.id} object={item} setPath={setPath} />)}</div></>;
  const alert = data.alerts.find((item) => item.objectId === object.id);
  return <>
    <PageTitle title={object.name} subtitle={`${object.district} · ${object.channelCount} каналов`}><RiskBadge level={object.level} /></PageTitle>
    <section className="panel"><div className="panel-head"><div><h2>Линейная карта пикетов</h2><p>Относительная схема — не географическая карта</p></div>{alert && <Link className="button primary" to={`/alerts/${alert.id}`} setPath={setPath}>Открыть предупреждение</Link>}</div><PicketMap channels={object.channels} alert={alert} /></section>
    <section className="panel"><div className="panel-head"><div><h2>Каналы объекта</h2><p>Значения, возраст и источник метаданных</p></div></div><ChannelTable channels={object.channels} /></section>
  </>;
}

function ObjectCard({ object, setPath }: { object: RiskObject; setPath: (path: string) => void }) {
  return <article className="object-card" onClick={() => go(`/objects/${object.id}`, setPath)}><div><span className="object-icon">⌘</span><RiskBadge level={object.level} /></div><h2>{object.name}</h2><p>{object.district} · {object.channelCount} каналов</p><footer><span>Максимальный риск</span><strong>{Math.round(object.probability * 100)}%</strong></footer></article>;
}

function ChannelTable({ channels }: { channels: RiskObject["channels"] }) {
  return <div className="table-wrap"><table><thead><tr><th>Канал</th><th>Пикет</th><th>Значение</th><th>Возраст и ТО</th><th>Источник</th></tr></thead><tbody>{channels.map((channel) => <tr key={channel.id}><td><b>{channel.name}</b><small>{channel.sensorType}</small></td><td>{channel.picketRaw ?? "Без пикета"}</td><td><span className={`sensor-state ${channel.state}`}>{channel.value ?? "—"}</span></td><td>{channel.deviceAgeYears != null ? `${channel.deviceAgeYears.toFixed(1)} года` : "Нет данных"}<small>{channel.maintenanceNote}</small></td><td><span className="source-tag">{channel.ageSource === "generated_demo" ? "Demo-оценка" : channel.ageSource === "first_seen" ? "По первому событию" : "Импорт"}</span></td></tr>)}</tbody></table></div>;
}

function AlertsPage({ data, path, setPath, onRefresh }: { data: AppData; path: string; setPath: (path: string) => void; onRefresh: () => Promise<void> }) {
  const id = path.split("/")[2];
  const alert = data.alerts.find((item) => item.id === id);
  if (!alert) return <><PageTitle title="Журнал предупреждений" subtitle="Пожарные риски и технические сбои — раздельно" /><section className="panel"><AlertTable alerts={data.alerts} setPath={setPath} /></section></>;
  return <AlertDetails alert={alert} sms={data.sms.filter((item) => item.episodeId === alert.episodeId)} setPath={setPath} onRefresh={onRefresh} />;
}

function AlertDetails({ alert, sms, setPath, onRefresh }: { alert: Alert; sms: AppData["sms"]; setPath: (path: string) => void; onRefresh: () => Promise<void> }) {
  const [message, setMessage] = useState("");
  const [decision, setDecision] = useState("maintenance");
  const [comment, setComment] = useState("");
  const act = async (action: "decision" | "request") => {
    if (action === "decision") await api.addDecision(alert.id, decision, comment);
    else await api.createRequest(alert.id, alert.recommendation);
    setMessage(action === "decision" ? "Решение сохранено" : "Заявка создана");
    await onRefresh();
  };
  return <>
    <PageTitle title={`${alertKindLabel(alert.kind)} · ${Math.round(alert.probability * 100)}%`} subtitle={`${alert.objectName} · эпизод ${alert.episodeId}`}><KindBadge alert={alert} /><RiskBadge level={alert.level} /></PageTitle>
    {alert.stale && <div className="notice warning">Показан последний успешный прогноз: ML-сервис временно недоступен.</div>}
    <div className="detail-grid">
      <section className="panel hero-alert"><div className={`risk-score level-${alert.level}`}><strong>{Math.round(alert.probability * 100)}%</strong><span>{riskLabel(alert.level)}</span></div><div><dl className="facts"><div><dt>Рассчитано</dt><dd>{formatDate(alert.calculatedAt)}</dd></div><div><dt>Модель</dt><dd>{alert.modelVersion}</dd></div><div><dt>Опасный участок</dt><dd>{alert.picketFrom ? `ПК ${alert.picketFrom.toFixed(2)}–${alert.picketTo?.toFixed(2)}` : "Не определён"}</dd></div><div><dt>Адресаты</dt><dd>{alert.recipients.join(", ")}</dd></div></dl></div></section>
      <section className="panel"><div className="panel-head"><div><h2>Динамика вероятности</h2><p>Накопленный риск по горизонтам</p></div></div><ProbabilityChart alert={alert} /></section>
    </div>
    <section className="panel"><div className="panel-head"><div><h2>Каналы и опасный диапазон</h2><p>Пикеты расположены в относительном масштабе</p></div></div><PicketMap channels={alert.channels} alert={alert} /></section>
    <div className="detail-grid thirds">
      <section className="panel"><h2>Факторы и объяснение</h2><div className="factor-list">{alert.factors.map((factor) => <div key={factor.label}><header><b>{factor.label}</b><strong>+{Math.round(factor.contribution * 100)}%</strong></header><p>{factor.detail}</p><i style={{ width: `${factor.contribution * 200}%` }} /></div>)}</div></section>
      <section className="panel"><h2>Рекомендация</h2><p className="recommendation">{alert.recommendation}</p><button className="primary" onClick={() => act("request")}>Создать заявку</button></section>
      <section className="panel"><h2>Демонстрационный контекст</h2><span className="source-tag">Mock-источник</span><p>{alert.context}</p></section>
    </div>
    <section className="panel"><div className="panel-head"><div><h2>Возраст и ТО</h2><p>Числовая оценка и источник показаны отдельно</p></div></div><ChannelTable channels={alert.channels} /></section>
    <div className="detail-grid">
      <section className="panel"><h2>Решение диспетчера</h2><label className="field">Результат проверки<select value={decision} onChange={(event) => setDecision(event.target.value)}><option value="confirmed_fire">Подтверждённый пожар</option><option value="smoke_without_fire">Задымление без пожара</option><option value="false_alarm">Ложное срабатывание</option><option value="sensor_malfunction">Техническая неисправность</option><option value="maintenance">Проверка / ТО</option><option value="unknown">Недостаточно данных</option></select></label><label className="field">Комментарий<textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Необязательно" /></label><button className="primary" onClick={() => act("decision")}>Сохранить решение</button>{message && <span className="success-message">✓ {message}</span>}</section>
      <section className="panel"><h2>История уровня</h2><div className="timeline">{alert.history.map((item, index) => <div key={index}><i className={`level-${item.toLevel}`} /><div><b>{item.fromLevel ? `${riskLabel(item.fromLevel)} → ` : "Создано: "}{riskLabel(item.toLevel)}</b><small>{formatDate(item.changedAt)}</small></div></div>)}</div></section>
    </div>
    <section className="panel"><div className="panel-head"><div><h2>Статусы SMS</h2><p>Получатели текущего уровня и доставка</p></div><Link to="/sms" setPath={setPath}>Весь журнал →</Link></div><SmsTable sms={sms} /></section>
  </>;
}

function RequestsPage({ data, onRefresh }: { data: AppData; onRefresh: () => Promise<void> }) {
  return <><PageTitle title="Заявки" subtitle="Превентивные проверки и техническое обслуживание" /><section className="panel"><div className="table-wrap"><table><thead><tr><th>ID / объект</th><th>Пикет</th><th>Рекомендация</th><th>Создана</th><th>Статус</th></tr></thead><tbody>{data.requests.map((request) => <tr key={request.id}><td><b>{request.id}</b><small>{request.objectName}</small></td><td>{request.picket ?? "—"}</td><td>{request.recommendation}</td><td>{formatDate(request.createdAt)}</td><td><select value={request.status} onChange={async (event) => { await api.updateRequest(request.id, event.target.value as RequestStatus); await onRefresh(); }}>{Object.entries(requestStatusName).map(([value, name]) => <option value={value} key={value}>{name}</option>)}</select></td></tr>)}</tbody></table></div>{!data.requests.length && <Empty>Заявок пока нет.</Empty>}</section></>;
}

function AnalyticsPage({ data }: { data: AppData }) {
  const primary = data.alerts[0];
  return <><PageTitle title="Аналитика" subtitle="Качество proxy-модели и динамика прогнозов" /><div className="notice info"><b>Важно:</b> показатели рассчитаны на временной proxy-разметке MVP и не являются подтверждённым качеством прогнозирования реальных пожаров.</div><div className="kpi-grid"><article className="kpi info"><span>ROC AUC</span><strong>{data.metrics.rocAuc.toFixed(2)}</strong><small>{data.metrics.modelVersion}</small></article><article className="kpi success"><span>Precision</span><strong>{Math.round(data.metrics.precision * 100)}%</strong><small>proxy-разметка</small></article><article className="kpi warning"><span>Recall</span><strong>{Math.round(data.metrics.recall * 100)}%</strong><small>proxy-разметка</small></article><article className="kpi"><span>Тревог / объект / сутки</span><strong>{data.metrics.alertsPerDay.toFixed(1)}</strong><small>демонстрационная выборка</small></article></div><div className="dashboard-grid"><section className="panel wide"><div className="panel-head"><div><h2>Динамика вероятностей</h2><p>{primary?.objectName}</p></div></div>{primary && <ProbabilityChart alert={primary} />}</section><section className="panel"><h2>Источник оценки</h2><p className="metric-source">{data.metrics.labelSource}</p><dl className="facts"><div><dt>Версия модели</dt><dd>{data.metrics.modelVersion}</dd></div><div><dt>Назначение</dt><dd>Демонстрация MVP</dd></div><div><dt>Ограничение</dt><dd>Нет журнала подтверждённых пожаров</dd></div></dl></section></div></>;
}

function SmsTable({ sms }: { sms: AppData["sms"] }) {
  return <div className="table-wrap"><table><thead><tr><th>Время</th><th>Эпизод</th><th>Роль / получатель</th><th>Сообщение</th><th>Статус</th></tr></thead><tbody>{sms.map((item) => <tr key={item.id}><td>{formatDate(item.sentAt)}</td><td><b>{item.episodeId}</b><small>{riskLabel(item.alertLevel)}</small></td><td><b>{item.role}</b><small>{item.recipientId}</small></td><td>{item.content}</td><td><span className={`delivery ${item.status}`}>{item.status === "delivered" ? "Доставлено" : item.status === "queued" ? "В очереди" : "Ошибка"}</span></td></tr>)}</tbody></table></div>;
}

function SmsPage({ data }: { data: AppData }) {
  return <><PageTitle title="Журнал SMS" subtitle="Ролевая рассылка, статусы доставки и дедупликация" /><div className="notice info">Повторы одного уровня и эпизода блокируются на период cooldown. Эскалация создаёт новую рассылку.</div><section className="panel"><SmsTable sms={data.sms} /></section></>;
}

export function App({ initialData, initialPath }: { initialData?: AppData; initialPath?: string }) {
  const [data, setData] = useState<AppData | undefined>(initialData);
  const [path, setPath] = useState(initialPath ?? (typeof window === "undefined" ? "/" : window.location.pathname));
  const [userRole, setUserRole] = useState<UserRole>(savedRole);
  const role = roles.find((item) => item.value === userRole)!;
  const changeRole = (value: UserRole) => {
    setUserRole(value);
    try { window.localStorage.setItem("fire-risk-role", value); } catch { /* storage may be disabled */ }
  };
  const refresh = async () => setData(await api.load());
  useEffect(() => { if (!initialData) void refresh(); }, []);
  useEffect(() => { const handler = () => setPath(window.location.pathname); window.addEventListener("popstate", handler); return () => window.removeEventListener("popstate", handler); }, []);
  const activeRoot = useMemo(() => path === "/" ? "/" : `/${path.split("/")[1]}`, [path]);
  if (!data) return <div className="loading">Загрузка данных…</div>;
  let page: React.ReactNode;
  if (path.startsWith("/objects")) page = <ObjectsPage data={data} path={path} setPath={setPath} />;
  else if (path.startsWith("/alerts")) page = <AlertsPage data={data} path={path} setPath={setPath} onRefresh={refresh} />;
  else if (path === "/requests") page = <RequestsPage data={data} onRefresh={refresh} />;
  else if (path === "/analytics") page = <AnalyticsPage data={data} />;
  else if (path === "/sms") page = <SmsPage data={data} />;
  else page = <Dashboard data={data} setPath={setPath} />;
  return <div className="app-shell"><aside className="sidebar"><div className="brand"><span>МК</span><div><b>Москоллектор</b><small>Аналитика рисков</small></div></div><nav>{nav.map(([href, label, icon]) => <Link key={href} to={href} setPath={setPath} className={activeRoot === href ? "active" : ""}><span>{icon}</span>{label}</Link>)}</nav><div className="sidebar-foot"><span className="online-dot" />Система работает<small>Модель: {data.metrics.modelVersion}</small></div></aside><main><div className="topbar"><div><span className="pulse" />Данные обновлены 2 мин назад</div><div className="top-user">{data.demo && <span className="demo-badge">DEMO</span>}<label className="role-switch">Роль<select aria-label="Текущая роль" value={userRole} onChange={(event) => changeRole(event.target.value as UserRole)}>{roles.map((item) => <option value={item.value} key={item.value}>{item.name}</option>)}</select></label><span className="avatar">{role.initials}</span><div><b>{role.name}</b><small>{role.scope}</small></div></div></div><div className="content">{page}</div></main></div>;
}
