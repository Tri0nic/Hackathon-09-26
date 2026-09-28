import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { alertKindLabel, allowedNavigation, countCriticalObjects, dashboardAlerts, dashboardDistrict, employees, formatDate, levelName, probabilityAtHorizon, profileFor, requestStatusName, riskLabel, smsDeliveryStatusName, smsProcessingStatusName, visibleObjectsFor } from "./domain";
import { Empty, KindBadge, PageTitle, PicketMap, ProbabilityChart, RiskBadge } from "./components";
import { ModelDemoPage } from "./ModelDemoPage";
import type { DashboardHorizon } from "./domain";
import type { Alert, AppData, Employee, ExecutorGroup, ExecutorRequestAction, MaintenanceRequest, RequestKind, RequestPriority, RequestStatus, RiskLevel, RiskObject, UserRole } from "./types";

const nav = [
  ["/", "Обзор", "▦"], ["/objects", "Объекты", "⌘"], ["/alerts", "Предупреждения", "△"],
  ["/requests", "Заявки", "▤"], ["/analytics", "Аналитика", "⌁"], ["/sms", "Журнал SMS", "✉"]
] as const;

const roles = [
  { value: "technician", name: "Техник", initials: "ТХ" },
  { value: "district_dispatcher", name: "Диспетчер района", initials: "ДР" },
  { value: "ods_dispatcher", name: "Диспетчер ОДС (главный)", initials: "ДО" },
  { value: "response_team", name: "Группа реагирования", initials: "ГР" }
] as const;

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

function PersonLink({ id, name, setPath }: { id?: string; name: string; setPath: (value: string) => void }) {
  const person = id ? employees.find((item) => item.id === id) : undefined;
  return person ? <Link to={`/profile/${person.id}`} setPath={setPath} className="person-link">{name}</Link> : <>{name}</>;
}

const horizonNames: Record<DashboardHorizon, string> = { now: "Сейчас", "6h": "6 часов", "12h": "12 часов", "24h": "24 часа" };
const riskLevels: RiskLevel[] = ["black", "red", "yellow", "green"];

function Dashboard({ data, role, setPath }: { data: AppData; role: UserRole; setPath: (path: string) => void }) {
  const [horizon, setHorizon] = useState<DashboardHorizon>("24h");
  const [district, setDistrict] = useState("all");
  const [level, setLevel] = useState<RiskLevel | "all">("all");
  const districts = [...new Set(data.objects.map((object) => object.district))];
  const activeDistrict = dashboardDistrict(role, district, districts);
  const alerts = dashboardAlerts(data.alerts, data.objects, activeDistrict, level);
  const objectIds = new Set(alerts.map((alert) => alert.objectId));
  const objects = data.objects.filter((object) => objectIds.has(object.id));
  const critical = countCriticalObjects(alerts);
  const openRequests = data.requests.filter((request) => objectIds.has(request.objectId) && !["completed", "rejected"].includes(request.status)).length;
  const primary = alerts[0];
  return <>
    <PageTitle title="Мониторинг рисков" subtitle={`Прогноз состояния инженерной инфраструктуры: ${horizonNames[horizon].toLowerCase()}`}>
      <button className="secondary">Обновить данные</button>
    </PageTitle>
    <div className="filters">
      <label>Горизонт <select aria-label="Горизонт прогноза" value={horizon} onChange={(event) => setHorizon(event.target.value as DashboardHorizon)}><option value="24h">24 часа</option><option value="12h">12 часов</option><option value="6h">6 часов</option><option value="now">Сейчас</option></select></label>
      {role === "ods_dispatcher" && <label>Район <select aria-label="Район" value={activeDistrict} onChange={(event) => setDistrict(event.target.value)}><option value="all">Все районы</option>{districts.map((item) => <option value={item} key={item}>{item}</option>)}</select></label>}
      <label>Уровень тревоги <select aria-label="Уровень тревоги" value={level} onChange={(event) => setLevel(event.target.value as RiskLevel | "all")}><option value="all">Все уровни</option>{riskLevels.map((item) => <option value={item} key={item}>{levelName[item]}</option>)}</select></label>
    </div>
    <div className="kpi-grid">
      <article className="kpi danger"><span>Критические риски</span><strong>{critical}</strong><small>требуют решения</small></article>
      <article className="kpi warning"><span>Активные предупреждения</span><strong>{alerts.length}</strong><small>в текущих эпизодах</small></article>
      <article className="kpi info"><span>Объекты под контролем</span><strong>{objects.length}</strong><small>{Math.max(0, objects.length - critical)} без критических отклонений</small></article>
      <article className="kpi success"><span>Открытые заявки</span><strong>{openRequests}</strong><small>профилактика и проверка</small></article>
    </div>
    <div className="dashboard-grid">
      <section className="panel wide"><div className="panel-head"><div><h2>Объекты внимания</h2><p>По максимальной вероятности активного риска</p></div><Link to="/objects" setPath={setPath}>Все объекты →</Link></div>
        <div className="table-wrap"><table><thead><tr><th>Объект</th><th>Район</th><th>Вероятность</th><th>Уровень</th></tr></thead><tbody>{objects.map((object) => { const alert = alerts.find((item) => item.objectId === object.id); return <tr key={object.id} className="clickable" onClick={() => go(`/objects/${object.id}`, setPath)}><td><b>{object.name}</b><small>{object.channelCount} каналов</small></td><td>{object.district}</td><td><strong>{Math.round((alert ? probabilityAtHorizon(alert, horizon) : object.probability) * 100)}%</strong></td><td><RiskBadge level={alert?.level ?? object.level} /></td></tr>; })}</tbody></table></div>
      </section>
      <section className="panel"><div className="panel-head"><div><h2>Динамика главного риска</h2><p>{primary?.objectName}</p></div></div>{primary ? <ProbabilityChart alert={primary} /> : <Empty>Нет предупреждений по выбранным фильтрам.</Empty>}</section>
    </div>
    <section className="panel"><div className="panel-head"><div><h2>Последние предупреждения</h2><p>Расчёты модели пожарного риска</p></div><Link to="/alerts" setPath={setPath}>Открыть журнал →</Link></div><AlertTable alerts={alerts} setPath={setPath} horizon={horizon} />{!alerts.length && <Empty>Нет предупреждений по выбранным фильтрам.</Empty>}</section>
  </>;
}

function AlertTable({ alerts, setPath, horizon }: { alerts: Alert[]; setPath: (path: string) => void; horizon?: DashboardHorizon }) {
  return <div className="table-wrap"><table><thead><tr><th>Время</th><th>Объект и тип</th><th>Вероятность</th><th>Уровень и горизонт</th></tr></thead><tbody>{alerts.map((alert) => <tr key={alert.id} className="clickable" onClick={() => go(`/alerts/${alert.id}`, setPath)}><td>{formatDate(alert.calculatedAt)}</td><td><b>{alert.objectName}</b><small>{alertKindLabel(alert.kind)} {alert.isDemo && <span className="demo-badge-inline">Демо</span>}</small></td><td><strong>{Math.round((horizon ? probabilityAtHorizon(alert, horizon) : alert.probability) * 100)}%</strong></td><td><RiskBadge level={alert.level} /></td></tr>)}</tbody></table></div>;
}

function ObjectsPage({ data, path, setPath }: { data: AppData; path: string; setPath: (path: string) => void }) {
  const id = path.split("/")[2];
  const object = data.objects.find((item) => item.id === id);
  if (!object) return <><PageTitle title="Объекты" subtitle="Инфраструктурные объекты и каналы мониторинга" /><div className="object-cards">{data.objects.map((item) => <ObjectCard key={item.id} object={item} setPath={setPath} />)}</div></>;
  const alert = data.alerts.find((item) => item.objectId === object.id);
  return <>
    <PageTitle title={object.name} subtitle={`${object.district} · ${object.channelCount} каналов`}><RiskBadge level={object.level} /></PageTitle>
    <section className="panel"><div className="panel-head"><div><h2>Линейная карта пикетов</h2><p>Относительная схема — не географическая карта</p></div>{alert && <Link className="button primary" to={`/alerts/${alert.id}`} setPath={setPath}>Открыть предупреждение</Link>}</div><PicketMap channels={object.channels} alert={alert} /></section>
    <section className="panel"><div className="panel-head"><div><h2>Каналы объекта</h2><p>Значения и возраст оборудования</p></div></div><ChannelTable channels={object.channels} /></section>
  </>;
}

function ObjectCard({ object, setPath }: { object: RiskObject; setPath: (path: string) => void }) {
  return <article className="object-card" onClick={() => go(`/objects/${object.id}`, setPath)}><div><span className="object-icon">⌘</span><RiskBadge level={object.level} /></div><h2>{object.name}</h2><p>{object.district} · {object.channelCount} каналов</p><footer><span>Максимальный риск</span><strong>{Math.round(object.probability * 100)}%</strong></footer></article>;
}

function ChannelTable({ channels }: { channels: RiskObject["channels"] }) {
  return <div className="table-wrap"><table><thead><tr><th>Канал</th><th>Пикет</th><th>Значение</th><th>Возраст и ТО</th></tr></thead><tbody>{channels.map((channel) => <tr key={channel.id}><td><b>{channel.name}</b><small>{channel.sensorType}</small></td><td>{channel.picketRaw ?? "Без пикета"}</td><td><span className={`sensor-state ${channel.state}`}>{channel.value ?? "—"}</span></td><td>{channel.deviceAgeYears != null ? `${channel.deviceAgeYears.toFixed(1)} года` : "Нет данных"}<small>{channel.maintenanceNote}</small></td></tr>)}</tbody></table></div>;
}

function AlertsPage({ data, path, setPath, onRefresh, role }: { data: AppData; path: string; setPath: (path: string) => void; onRefresh: () => Promise<void>; role: UserRole }) {
  const id = path.split("/")[2];
  const alert = data.alerts.find((item) => item.id === id);
  if (!alert) return <><PageTitle title="Журнал предупреждений" subtitle="Прогнозы пожарного риска по объектам" /><section className="panel"><AlertTable alerts={data.alerts} setPath={setPath} /></section></>;
  return <AlertDetails alert={alert} sms={data.sms.filter((item) => item.episodeId === alert.episodeId)} requests={data.requests} setPath={setPath} onRefresh={onRefresh} role={role} />;
}

function AlertDetails({ alert, sms, requests, setPath, onRefresh, role }: { alert: Alert; sms: AppData["sms"]; requests: AppData["requests"]; setPath: (path: string) => void; onRefresh: () => Promise<void>; role: UserRole }) {
  const [message, setMessage] = useState("");
  const [decision, setDecision] = useState("maintenance");
  const [comment, setComment] = useState("");
  const act = async () => {
    await api.addDecision(alert.id, decision, comment);
    setMessage("Решение сохранено");
    await onRefresh();
  };
  return <>
    <PageTitle title={`${alertKindLabel(alert.kind)} · ${Math.round(alert.probability * 100)}%`} subtitle={`${alert.objectName} · Технический ID эпизода: ${alert.episodeId}`}><KindBadge alert={alert} />{alert.isDemo && <span className="demo-badge-inline">Демо</span>}<RiskBadge level={alert.level} /></PageTitle>
    {alert.stale && <div className="notice warning">Показан последний успешный прогноз: ML-сервис временно недоступен.</div>}
    <div className="detail-grid">
      <section className="panel hero-alert"><div className={`risk-score level-${alert.level}`}><strong>{Math.round(alert.probability * 100)}%</strong><span>{riskLabel(alert.level)}</span></div><div><dl className="facts"><div><dt>Рассчитано</dt><dd>{formatDate(alert.calculatedAt)}</dd></div><div><dt>Опасный участок</dt><dd>{alert.picketFrom ? `ПК ${alert.picketFrom.toFixed(2)}–${alert.picketTo?.toFixed(2)}` : "Не определён"}</dd></div></dl></div></section>
      <section className="panel"><div className="panel-head"><div><h2>Динамика вероятности</h2><p>Накопленный риск по горизонтам</p></div></div><ProbabilityChart alert={alert} /></section>
    </div>
    <section className="panel"><div className="panel-head"><div><h2>Каналы и опасный диапазон</h2><p>Пикеты расположены в относительном масштабе</p></div></div><PicketMap channels={alert.channels} alert={alert} /></section>
    <div className="detail-grid thirds">
      <section className="panel"><h2>Факторы и объяснение</h2><div className="factor-list">{alert.factors.map((factor, index) => <div key={`${factor.label}-${index}`}><header><b>{factor.label}</b><strong>{factor.contribution >= 0 ? "+" : "−"}{Math.round(Math.abs(factor.contribution) * 100)}%</strong></header><p>{factor.detail}</p><i style={{ width: `${Math.min(100, Math.abs(factor.contribution) * 100)}%` }} /></div>)}</div></section>
      <section className="panel"><h2>Рекомендация</h2><p className="recommendation">{alert.recommendation}</p>{(role === "district_dispatcher" || role === "ods_dispatcher") && <Link className="button primary" to={`/alerts/${alert.id}/request`} setPath={setPath}>Создать заявку</Link>}</section>
      <section className="panel"><h2>Демонстрационный контекст</h2><p>{alert.context}</p></section>
    </div>
    <section className="panel"><div className="panel-head"><div><h2>Возраст и ТО</h2><p>Числовая оценка и источник показаны отдельно</p></div></div><ChannelTable channels={alert.channels} /></section>
    <div className="detail-grid">
      <section className="panel"><h2>Решение диспетчера</h2><label className="field">Результат проверки<select value={decision} onChange={(event) => setDecision(event.target.value)}><option value="confirmed_fire">Подтверждённый пожар</option><option value="smoke_without_fire">Задымление без пожара</option><option value="false_alarm">Ложное срабатывание</option><option value="sensor_malfunction">Техническая неисправность</option><option value="maintenance">Проверка / ТО</option><option value="unknown">Недостаточно данных</option></select></label><label className="field">Комментарий<textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Необязательно" /></label><button className="primary" onClick={act}>Сохранить решение</button>{message && <span className="success-message">✓ {message}</span>}</section>
      <section className="panel"><h2>История уровня</h2><div className="timeline">{alert.history.map((item, index) => <div key={index}><i className={`level-${item.toLevel}`} /><div><b>{item.fromLevel ? `${riskLabel(item.fromLevel)} → ` : "Создано: "}{riskLabel(item.toLevel)}</b><small>{formatDate(item.changedAt)}</small></div></div>)}</div></section>
    </div>
    <section className="panel"><div className="panel-head"><div><h2>Статусы SMS</h2><p>Уведомления по созданным заявкам</p></div><Link to="/sms" setPath={setPath}>Весь журнал →</Link></div><SmsTable sms={sms} alerts={[alert]} requests={requests} setPath={setPath} /></section>
  </>;
}

function RequestForm({ alert, role, setPath, onRefresh, alerts, onAlertChange, cancelTo }: { alert: Alert; role: UserRole; setPath: (path: string) => void; onRefresh: () => Promise<void>; alerts?: Alert[]; onAlertChange?: (id: string) => void; cancelTo?: string }) {
  const ods = role === "ods_dispatcher";
  const [requestKind, setRequestKind] = useState<RequestKind>(ods ? "emergency" : "repair");
  const [executorGroup, setExecutorGroup] = useState<ExecutorGroup>(ods ? "response_team" : "technician");
  const [priority, setPriority] = useState<RequestPriority>(ods ? "emergency" : "normal");
  const [description, setDescription] = useState(alert.recommendation);
  const [dueAt, setDueAt] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!description.trim()) { setError("Укажите описание неисправности"); return; }
    await api.createRequest({ alertId: alert.id, requestKind, executorGroup, priority, description: description.trim(), dueAt: dueAt || undefined, comment: comment.trim() || undefined, creatorRole: ods ? "ods_dispatcher" : "district_dispatcher" });
    await onRefresh();
    go("/requests", setPath);
  };
  return <><PageTitle title={ods ? "Экстренная заявка ОДС" : "Создание заявки"} subtitle={`${alert.objectName} · ${alertKindLabel(alert.kind)}`} />
    <form className="panel request-form" onSubmit={submit}>
      <div className="form-grid">
        {alerts && <label className="field">Объект и предупреждение<select value={alert.id} onChange={(event) => onAlertChange?.(event.target.value)}>{alerts.map((item) => <option key={item.id} value={item.id}>{item.objectName}</option>)}</select></label>}
        <label className="field">Тип заявки<select value={requestKind} disabled={ods} onChange={(e) => setRequestKind(e.target.value as RequestKind)}>{!ods && <><option value="inspection">Осмотр</option><option value="repair">Ремонт</option></>}<option value="emergency">Экстренный выезд</option></select></label>
        <label className="field">Группа исполнителей<select value={executorGroup} disabled={ods} onChange={(e) => setExecutorGroup(e.target.value as ExecutorGroup)}><option value="technician">Техники</option><option value="response_team">Группа быстрого реагирования</option></select></label>
        <label className="field">Приоритет<select value={priority} disabled={ods} onChange={(e) => setPriority(e.target.value as RequestPriority)}>{!ods && <><option value="normal">Обычный</option><option value="high">Высокий</option></>}<option value="emergency">Экстренный</option></select></label>
        <label className="field">Срок выполнения<input type="datetime-local" value={dueAt} onChange={(e) => setDueAt(e.target.value)} /></label>
      </div>
      <label className="field">Описание неисправности<textarea required value={description} onChange={(e) => setDescription(e.target.value)} /></label>
      <label className="field">Комментарий<textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Дополнительная информация" /></label>
      <div className="form-actions"><Link to={cancelTo ?? `/alerts/${alert.id}`} setPath={setPath} className="button secondary">Отмена</Link><button className="primary" type="submit">Создать и уведомить исполнителей</button></div>
      {error && <div className="notice warning">{error}</div>}
    </form></>;
}

function NewRequestPage({ data, role, setPath, onRefresh }: { data: AppData; role: UserRole; setPath: (path: string) => void; onRefresh: () => Promise<void> }) {
  const [alertId, setAlertId] = useState(data.alerts[0]?.id ?? "");
  const alert = data.alerts.find((item) => item.id === alertId) ?? data.alerts[0];
  if (!alert) return <><PageTitle title="Создание заявки" subtitle="Нет доступных предупреждений" /><Empty>Для доступных объектов предупреждений нет.</Empty></>;
  return <RequestForm key={alert.id} alert={alert} role={role} setPath={setPath} onRefresh={onRefresh} alerts={data.alerts} onAlertChange={setAlertId} cancelTo="/requests" />;
}

type RequestTableMode = "dispatcher" | "available" | "mine" | "busy";
type DialogAction = "claim" | ExecutorRequestAction;

function RequestActionDialog({ request, employee, action, onClose, onRefresh }: { request: MaintenanceRequest; employee: Employee; action: DialogAction; onClose: () => void; onRefresh: () => Promise<void> }) {
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const titles: Record<DialogAction, string> = { claim: "Взять заявку в работу?", comment: "Добавить комментарий", release: "Снять заявку с себя?", complete: "Завершить заявку?", cancel: "Отменить заявку?" };
  const submitLabels: Record<DialogAction, string> = { claim: "Да, взять в работу", comment: "Сохранить комментарий", release: "Снять с себя", complete: "Отметить выполненной", cancel: "Отменить заявку" };
  const needsText = action === "comment" || action === "cancel";
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (needsText && !comment.trim()) { setError(action === "cancel" ? "Укажите причину отмены" : "Введите комментарий"); return; }
    setBusy(true); setError("");
    try {
      if (action === "claim") await api.claimRequest(request.id, employee);
      else await api.executeRequestAction(request.id, employee, action, comment.trim());
      await onRefresh();
      onClose();
    } catch (cause) {
      await onRefresh();
      setError(cause instanceof Error && !cause.message.startsWith("API ") ? cause.message : "Не удалось выполнить действие. Возможно, заявку уже изменил другой сотрудник.");
    } finally { setBusy(false); }
  };
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="request-action-title">
    <form onSubmit={submit}>
      <div className="modal-head"><div><h2 id="request-action-title">{titles[action]}</h2><p>{request.publicId} · {request.objectName}</p></div><button type="button" className="icon-button" aria-label="Закрыть" onClick={onClose}>×</button></div>
      <dl className="action-summary"><div><dt>Заявка</dt><dd>{request.description}</dd></div><div><dt>Исполнитель</dt><dd>{employee.name}</dd></div></dl>
      {action !== "claim" && <label className="field">{action === "cancel" ? "Причина отмены" : action === "comment" ? "Комментарий о выполненных работах" : "Комментарий (необязательно)"}<textarea autoFocus value={comment} onChange={(event) => setComment(event.target.value)} placeholder={action === "comment" ? "Опишите, что было проверено или сделано" : "Добавьте пояснение к действию"} /></label>}
      {action === "release" && <p className="modal-hint">После подтверждения заявка вернётся в общий пул исполнителей.</p>}
      {action === "cancel" && <p className="modal-hint warning-text">Заявка будет закрыта для всех исполнителей.</p>}
      {error && <div className="notice warning">{error}</div>}
      <div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Назад</button><button type="submit" className={action === "cancel" ? "danger-button" : "primary"} disabled={busy}>{busy ? "Сохранение…" : submitLabels[action]}</button></div>
    </form>
  </section></div>;
}

function RequestTable({ requests, alerts, mode, employee, onRefresh, setPath }: { requests: AppData["requests"]; alerts: AppData["alerts"]; mode: RequestTableMode; employee?: Employee; onRefresh: () => Promise<void>; setPath: (path: string) => void }) {
  const [dialog, setDialog] = useState<{ request: MaintenanceRequest; action: DialogAction }>();
  const ownAction = (request: MaintenanceRequest, action: ExecutorRequestAction) => setDialog({ request, action });
  return <><div className="table-wrap"><table><thead><tr><th>ID / объект</th><th>Описание</th><th>Группа</th><th>Приоритет</th><th>Уровень тревоги</th><th>Кто взял задачу</th><th>Статус / действия</th></tr></thead><tbody>{requests.map((request) => { const alert = alerts.find((item) => item.id === request.alertId); return <tr key={request.id}><td><b>{request.publicId}</b><small>{request.objectName}</small></td><td>{request.description}<small>{request.picket ?? "Пикет не указан"}</small>{request.comment && <div className="request-original-comment"><b>Комментарий к заявке</b><p>{request.comment}</p></div>}{request.comments?.length > 0 && <details className="request-comments"><summary>Комментарии исполнителей ({request.comments.length})</summary>{request.comments.map((item) => <article key={item.id}><b><PersonLink id={item.employeeId} name={item.employeeName} setPath={setPath} /></b><time>{formatDate(item.createdAt)}</time><p>{item.text}</p></article>)}</details>}</td><td>{request.executorGroup === "technician" ? "Техники" : "ГБР"}</td><td>{request.priority === "emergency" ? "Экстренный" : request.priority === "high" ? "Высокий" : "Обычный"}</td><td>{alert ? <RiskBadge level={alert.level} /> : <span className="muted">—</span>}</td><td>{request.assigneeName ? <PersonLink id={request.assigneeId} name={request.assigneeName} setPath={setPath} /> : <span className="muted">Не назначен</span>}</td><td>{mode === "dispatcher" ? <select value={request.status} onChange={async (event) => { await api.updateRequest(request.id, event.target.value as RequestStatus); await onRefresh(); }}>{Object.entries(requestStatusName).map(([value, name]) => <option value={value} key={value}>{name}</option>)}</select> : mode === "available" ? <button className="primary compact" aria-haspopup="dialog" onClick={() => employee && setDialog({ request, action: "claim" })}>Взять в работу</button> : mode === "mine" && request.status === "in_progress" ? <div className="request-actions"><button className="secondary compact" aria-haspopup="dialog" onClick={() => ownAction(request, "comment")}>Добавить комментарий</button><button className="icon-button release" aria-label="Снять с себя" title="Снять с себя" aria-haspopup="dialog" onClick={() => ownAction(request, "release")}>×</button><button className="success-button compact" aria-haspopup="dialog" onClick={() => ownAction(request, "complete")}>Выполнено</button><button className="danger-button compact" aria-haspopup="dialog" onClick={() => ownAction(request, "cancel")}>Отклонить</button></div> : requestStatusName[request.status]}</td></tr>; })}</tbody></table></div>{dialog && employee && <RequestActionDialog request={dialog.request} employee={employee} action={dialog.action} onClose={() => setDialog(undefined)} onRefresh={onRefresh} />}</>;
}

function RequestsPage({ data, role, employee, onRefresh, setPath }: { data: AppData; role: UserRole; employee?: Employee; onRefresh: () => Promise<void>; setPath: (path: string) => void }) {
  const dispatcher = role === "district_dispatcher" || role === "ods_dispatcher";
  if (dispatcher) return <><PageTitle title="Заявки" subtitle="Контроль исполнения и технического обслуживания"><Link className="button primary" to="/requests/new" setPath={setPath}>Создать заявку</Link></PageTitle><section className="panel"><RequestTable requests={data.requests} alerts={data.alerts} mode="dispatcher" employee={employee} onRefresh={onRefresh} setPath={setPath} />{!data.requests.length && <Empty>Заявок пока нет.</Empty>}</section></>;
  const group = role as ExecutorGroup;
  const relevant = data.requests.filter((request) => request.executorGroup === group);
  const mine = relevant.filter((request) => request.assigneeId === employee?.id);
  const available = relevant.filter((request) => !request.assigneeId && !["completed", "rejected"].includes(request.status));
  const busy = relevant.filter((request) => request.assigneeId && request.assigneeId !== employee?.id);
  return <><PageTitle title={role === "technician" ? "Рабочее место техника" : "Рабочее место ГБР"} subtitle={employee?.name ?? "Выберите сотрудника"} />
    <section className="panel"><div className="panel-head"><div><h2>Доступные заявки</h2><p>Первый исполнитель, взявший заявку, становится ответственным</p></div></div><RequestTable requests={available} alerts={data.alerts} mode="available" employee={employee} onRefresh={onRefresh} setPath={setPath} />{!available.length && <Empty>Свободных заявок нет.</Empty>}</section>
    <section className="panel"><div className="panel-head"><div><h2>Мои заявки</h2><p>Закреплены за выбранным сотрудником</p></div></div><RequestTable requests={mine} alerts={data.alerts} mode="mine" employee={employee} onRefresh={onRefresh} setPath={setPath} />{!mine.length && <Empty>У сотрудника пока нет заявок.</Empty>}</section>
    <section className="panel"><div className="panel-head"><div><h2>Занятые заявки группы</h2><p>Уже закреплены за коллегами</p></div></div><RequestTable requests={busy} alerts={data.alerts} mode="busy" employee={employee} onRefresh={onRefresh} setPath={setPath} />{!busy.length && <Empty>Занятых коллегами заявок нет.</Empty>}</section></>;
}

function ProfilePage({ role, employee, objects }: { role: UserRole; employee?: Employee; objects: RiskObject[] }) {
  const profile = profileFor(role, employee, objects);
  const roleName = roles.find((item) => item.value === role)?.name ?? role;
  return <><PageTitle title="Профиль сотрудника" subtitle={roleName} /><div className="profile-grid"><section className="panel profile-card"><div className="profile-avatar">{profile.name.split(" ").slice(0, 2).map((part) => part[0]).join("")}</div><h2>{profile.name}</h2><p>{roleName}</p></section><section className="panel"><h2>Районы ответственности</h2><div className="profile-tags">{profile.districts.map((district) => <span key={district}>{district}</span>)}</div></section><section className="panel profile-objects"><h2>Объекты</h2>{profile.objects.map((object) => <article key={object.id}><b>{object.name}</b><small>{object.district}</small></article>)}</section></div></>;
}

function EmployeeProfilePage({ id, objects, availableEmployees }: { id: string; objects: RiskObject[]; availableEmployees: Employee[] }) {
  const employee = availableEmployees.find((item) => item.id === id);
  if (!employee) return <><PageTitle title="Сотрудник не найден" subtitle="Профиль отсутствует" /><Empty>Проверьте ссылку на сотрудника.</Empty></>;
  const roleName = employee.group === "technician" ? "Техник" : "Группа быстрого реагирования";
  const assignedObjects = objects.filter((object) => employee.objectIds.includes(object.id));
  return <><PageTitle title="Профиль сотрудника" subtitle={roleName} /><div className="profile-grid"><section className="panel profile-card"><div className="profile-avatar">{employee.name.split(" ").slice(0, 2).map((part) => part[0]).join("")}</div><h2>{employee.name}</h2><p>{roleName}</p></section><section className="panel"><h2>Районы ответственности</h2><div className="profile-tags">{employee.districts.map((district) => <span key={district}>{district}</span>)}</div></section><section className="panel profile-objects"><h2>Объекты</h2>{assignedObjects.map((object) => <article key={object.id}><b>{object.name}</b><small>{object.district}</small></article>)}</section></div></>;
}

function AnalyticsPage({ data }: { data: AppData }) {
  const primary = data.alerts[0];
  return <><PageTitle title="Аналитика" subtitle="Качество proxy-модели и динамика прогнозов" /><div className="notice info"><b>Важно:</b> показатели рассчитаны на временной proxy-разметке MVP и не являются подтверждённым качеством прогнозирования реальных пожаров.</div><div className="kpi-grid"><article className="kpi info"><span>ROC AUC</span><strong>{data.metrics.rocAuc.toFixed(2)}</strong><small>{data.metrics.modelVersion}</small></article><article className="kpi success"><span>Precision</span><strong>{Math.round(data.metrics.precision * 100)}%</strong><small>proxy-разметка</small></article><article className="kpi warning"><span>Recall</span><strong>{Math.round(data.metrics.recall * 100)}%</strong><small>proxy-разметка</small></article><article className="kpi"><span>Тревог / объект / сутки</span><strong>{data.metrics.alertsPerDay.toFixed(1)}</strong><small>демонстрационная выборка</small></article></div><div className="dashboard-grid"><section className="panel wide"><div className="panel-head"><div><h2>Динамика вероятностей</h2><p>{primary?.objectName}</p></div></div>{primary && <ProbabilityChart alert={primary} />}</section><section className="panel"><h2>Источник оценки</h2><p className="metric-source">{data.metrics.labelSource}</p><dl className="facts"><div><dt>Версия модели</dt><dd>{data.metrics.modelVersion}</dd></div><div><dt>Назначение</dt><dd>Демонстрация MVP</dd></div><div><dt>Ограничение</dt><dd>Нет журнала подтверждённых пожаров</dd></div></dl></section></div></>;
}

function SmsTable({ sms, alerts, requests, setPath }: { sms: AppData["sms"]; alerts: AppData["alerts"]; requests: AppData["requests"]; setPath: (path: string) => void }) {
  const incidentsWithAssignee = new Set<string>();
  return <div className="table-wrap sms-table"><table><thead><tr><th>Время</th><th>Объект и тип</th><th>Уровень происшествия</th><th>Получатель</th><th>Причина</th><th>Ответственный</th><th>Доставка</th><th>Обработка</th></tr></thead><tbody>{sms.map((item) => {
    const alert = alerts.find((candidate) => candidate.episodeId === item.episodeId);
    const request = requests.find((candidate) => candidate.id === item.requestId);
    const incidentKey = item.episodeId;
    const showAssignee = Boolean(item.assigneeName) && !incidentsWithAssignee.has(incidentKey);
    if (showAssignee) incidentsWithAssignee.add(incidentKey);
    return <tr key={item.id} className="clickable sms-row" onClick={(event) => { if (!(event.target as HTMLElement).closest("a")) go(`/sms/${item.id}`, setPath); }}>
      <td>{formatDate(item.sentAt)}</td>
      <td><Link to={`/sms/${item.id}`} setPath={setPath}><b>{alert?.objectName ?? item.episodeTitle}</b><small>{alert ? alertKindLabel(alert.kind) : "Событие"}</small></Link></td>
      <td><span className={`risk-badge level-${item.alertLevel}`}><i />{riskLabel(item.alertLevel)}</span></td>
      <td><b><PersonLink id={item.recipientId} name={item.recipientName} setPath={setPath} /></b></td>
      <td>{item.incidentSummary}</td>
      <td>{showAssignee && item.assigneeName ? <PersonLink id={request?.assigneeId} name={item.assigneeName} setPath={setPath} /> : <span className="muted">—</span>}</td>
      <td><span className={`delivery ${item.status}`}>{smsDeliveryStatusName[item.status]}</span></td>
      <td><span className={`processing ${item.processingStatus}`}>{smsProcessingStatusName[item.processingStatus]}</span></td>
    </tr>;
  })}</tbody></table></div>;
}

function SmsPage({ data, setPath }: { data: AppData; setPath: (path: string) => void }) {
  return <><PageTitle title="Журнал SMS" subtitle="" /><section className="panel"><SmsTable sms={data.sms} alerts={data.alerts} requests={data.requests} setPath={setPath} /></section></>;
}

function SmsDetailsPage({ data, id, setPath }: { data: AppData; id: string; setPath: (path: string) => void }) {
  const sms = data.sms.find((item) => item.id === id);
  if (!sms) return <><PageTitle title="SMS не найдено" subtitle="Запись отсутствует или была удалена" /><Link to="/sms" setPath={setPath}>← Назад в журнал SMS</Link></>;
  const alert = data.alerts.find((item) => item.episodeId === sms.episodeId);
  const objectName = alert?.objectName ?? sms.episodeTitle;
  const subject = `${alert ? alertKindLabel(alert.kind) : "Событие"}: ${objectName}`;
  const location = alert?.picketFrom != null ? `ПК ${alert.picketFrom.toFixed(2)}–${alert.picketTo?.toFixed(2)}` : "Участок не определён";
  const stateName = (state?: string) => state === "danger" ? "Опасное значение" : state === "warning" ? "Требует внимания" : state === "malfunction" ? "Неисправность" : "Норма";
  return <>
    <div className="mail-back"><Link to="/sms" setPath={setPath}>← Назад в журнал SMS</Link></div>
    <section className="panel mail-window">
      <div className="mail-toolbar"><span>SMS-уведомление</span><span className={`delivery ${sms.status}`}>{smsDeliveryStatusName[sms.status]}</span></div>
      <h1>{subject}</h1>
      <div className="mail-meta"><div className="mail-avatar">МК</div><dl><div><dt>От:</dt><dd>Система мониторинга рисков АО «Москоллектор»</dd></div><div><dt>Кому:</dt><dd><PersonLink id={sms.recipientId} name={sms.recipientName} setPath={setPath} /></dd></div><div><dt>Дата:</dt><dd>{formatDate(sms.sentAt)}</dd></div><div><dt>Тема:</dt><dd>{subject}</dd></div></dl></div>
      <div className="mail-body">
        <p>Автоматическое уведомление о событии на объекте инженерной инфраструктуры.</p>
        <div className="mail-summary"><div><span>Объект</span><b>{objectName}</b></div><div><span>Местоположение</span><b>{location}</b></div><div><span>Состояние</span><b>{riskLabel(sms.alertLevel)}</b></div><div><span>Обработка</span><b>{smsProcessingStatusName[sms.processingStatus]}</b></div></div>
        <h2>Причина уведомления</h2><p>{sms.incidentSummary}</p>
        <h2>Датчики и состояние</h2>
        <div className="mail-sensors">{alert?.channels.map((channel) => <div key={channel.id}><div><b>{channel.name}</b><small>{channel.sensorType} · {stateName(channel.state)}</small></div><strong>{channel.value ?? "Нет данных"}</strong></div>) ?? <p className="muted">Данные датчиков отсутствуют.</p>}</div>
        <h2>Рекомендация</h2><p className="recommendation">{alert?.recommendation ?? sms.content}</p>
        <div className="mail-original"><b>Текст отправленного SMS</b><p>{sms.content}</p></div>
      </div>
    </section>
  </>;
}

export function App({ initialData, initialPath, initialRole }: { initialData?: AppData; initialPath?: string; initialRole?: UserRole }) {
  const [data, setData] = useState<AppData | undefined>(initialData);
  const [path, setPath] = useState(initialPath ?? (typeof window === "undefined" ? "/" : window.location.pathname));
  const [userRole, setUserRole] = useState<UserRole>(initialRole ?? savedRole);
  const [employeeId, setEmployeeId] = useState("");
  const role = roles.find((item) => item.value === userRole)!;
  const roleEmployees = employees.filter((item) => item.group === userRole);
  const selectedEmployee = roleEmployees.find((item) => item.id === employeeId) ?? roleEmployees[0];
  const visibleNav = nav.filter(([href]) => allowedNavigation(userRole).includes(href));
  const changeRole = (value: UserRole) => {
    setUserRole(value);
    setEmployeeId("");
    try { window.localStorage.setItem("fire-risk-role", value); } catch { /* storage may be disabled */ }
    if (!allowedNavigation(value).includes(path === "/" ? "/" : `/${path.split("/")[1]}`)) go(allowedNavigation(value)[0], setPath);
  };
  const refresh = async () => setData(await api.load());
  useEffect(() => { if (!initialData) void refresh(); }, []);
  useEffect(() => { const handler = () => setPath(window.location.pathname); window.addEventListener("popstate", handler); return () => window.removeEventListener("popstate", handler); }, []);
  const requestedRoot = useMemo(() => path === "/" ? "/" : `/${path.split("/")[1]}`, [path]);
  const effectivePath = allowedNavigation(userRole).includes(requestedRoot) ? path : allowedNavigation(userRole)[0];
  const activeRoot = effectivePath === "/" ? "/" : `/${effectivePath.split("/")[1]}`;
  useEffect(() => {
    if (path !== effectivePath && typeof window !== "undefined") {
      window.history.replaceState({}, "", effectivePath);
      setPath(effectivePath);
    }
  }, [path, effectivePath]);
  if (!data) return <div className="loading">Загрузка данных…</div>;
  let page: React.ReactNode;
  const visibleObjects = visibleObjectsFor(userRole, selectedEmployee, data.objects);
  const visibleObjectIds = new Set(visibleObjects.map((object) => object.id));
  const visibleEmployees = employees.filter((employee) => employee.objectIds.some((objectId) => visibleObjectIds.has(objectId)));
  const scopedData = { ...data, objects: visibleObjects, alerts: data.alerts.filter((alert) => visibleObjectIds.has(alert.objectId)), requests: data.requests.filter((request) => visibleObjectIds.has(request.objectId)), sms: data.sms.filter((item) => data.alerts.some((alert) => alert.episodeId === item.episodeId && visibleObjectIds.has(alert.objectId))) };
  const requestMatch = effectivePath.match(/^\/alerts\/([^/]+)\/request$/);
  if (requestMatch && (userRole === "district_dispatcher" || userRole === "ods_dispatcher")) {
    const alert = scopedData.alerts.find((item) => item.id === requestMatch[1]);
    page = alert ? <RequestForm alert={alert} role={userRole} setPath={setPath} onRefresh={refresh} /> : <Empty>Предупреждение не найдено.</Empty>;
  }
  else if (effectivePath === "/requests/new" && (userRole === "district_dispatcher" || userRole === "ods_dispatcher")) page = <NewRequestPage data={scopedData} role={userRole} setPath={setPath} onRefresh={refresh} />;
  else if (effectivePath.startsWith("/objects")) page = <ObjectsPage data={scopedData} path={effectivePath} setPath={setPath} />;
  else if (effectivePath.startsWith("/alerts")) page = <AlertsPage data={scopedData} path={effectivePath} setPath={setPath} onRefresh={refresh} role={userRole} />;
  else if (effectivePath === "/requests") page = <RequestsPage data={scopedData} role={userRole} employee={selectedEmployee} onRefresh={refresh} setPath={setPath} />;
  else if (effectivePath === "/model-demo") page = <ModelDemoPage navigate={(next) => go(next, setPath)} onRefresh={refresh} role={userRole} />;
  else if (effectivePath.startsWith("/profile/")) page = <EmployeeProfilePage id={effectivePath.split("/")[2]} objects={scopedData.objects} availableEmployees={visibleEmployees} />;
  else if (effectivePath === "/profile") page = <ProfilePage role={userRole} employee={selectedEmployee} objects={data.objects} />;
  else if (effectivePath === "/analytics") page = <AnalyticsPage data={scopedData} />;
  else if (effectivePath.startsWith("/sms/")) page = <SmsDetailsPage data={scopedData} id={effectivePath.split("/")[2]} setPath={setPath} />;
  else if (effectivePath === "/sms") page = <SmsPage data={scopedData} setPath={setPath} />;
  else page = <Dashboard data={scopedData} role={userRole} setPath={setPath} />;
  const currentProfile = profileFor(userRole, selectedEmployee, data.objects);
  return <div className="app-shell"><aside className="sidebar"><div className="brand"><span>МК</span><div><b>Москоллектор</b><small>Контроль инфраструктуры</small></div></div><nav>{visibleNav.map(([href, label, icon]) => <Link key={href} to={href} setPath={setPath} className={activeRoot === href ? "active" : ""}><span>{icon}</span>{label}</Link>)}</nav><div className="sidebar-foot"><Link to="/model-demo" setPath={setPath} className={activeRoot === "/model-demo" ? "active" : ""}><span>◇</span>Демонстрация модели</Link></div></aside><main><div className="topbar"><div><span className="pulse" />Данные обновлены 2 мин назад</div><div className="top-user"><label className="role-switch">Роль<select aria-label="Текущая роль" value={userRole} onChange={(event) => changeRole(event.target.value as UserRole)}>{roles.map((item) => <option value={item.value} key={item.value}>{item.name}</option>)}</select></label>{roleEmployees.length > 0 && <label className="role-switch">Сотрудник<select aria-label="Текущий сотрудник" value={selectedEmployee?.id} onChange={(event) => setEmployeeId(event.target.value)}>{roleEmployees.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>}<Link to="/profile" setPath={setPath} className="profile-link"><span className="avatar">{role.initials}</span><b>{currentProfile.name}</b></Link></div></div><div className="content">{page}</div></main></div>;
}
