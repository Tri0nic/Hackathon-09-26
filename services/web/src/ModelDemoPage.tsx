import { useEffect, useReducer } from "react";
import type { Dispatch } from "react";
import { api } from "./api";
import { PageTitle } from "./components";
import { formatDate } from "./domain";
import { canPublishModelDemo, initialModelDemoState, modelDemoPublicationPath, modelDemoReducer, modelDemoScenarioLabel } from "./modelDemo";
import type { ModelDemoAction, ModelDemoState } from "./modelDemo";
import type { UserRole } from "./types";

const percent = (value: number) => `${Math.round(value * 100)}%`;
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "Не удалось выполнить операцию";
const sensorDisplayName = (sensor: { id: string; name: string; sensorType: string }) => sensor.name.length > 60 ? `${sensor.sensorType} · канал ${sensor.id}` : sensor.name;

export function ModelDemoPage({ navigate, onRefresh, role, initialState, sharedState, sharedDispatch }: { navigate: (path: string) => void; onRefresh: () => Promise<void>; role: UserRole; initialState?: ModelDemoState; sharedState?: ModelDemoState; sharedDispatch?: Dispatch<ModelDemoAction> }) {
  const [localState, localDispatch] = useReducer(modelDemoReducer, initialState ?? initialModelDemoState);
  const state = sharedState ?? localState;
  const dispatch = sharedDispatch ?? localDispatch;
  const scenario = state.scenarios[state.index];

  useEffect(() => {
    if (initialState || state.scenarios.length > 0) return;
    api.listModelDemoScenarios().then((scenarios) => dispatch({ type: "load-success", scenarios })).catch((error) => dispatch({ type: "failure", message: errorMessage(error) }));
  }, [dispatch, initialState, state.scenarios.length]);

  const predict = async () => {
    if (!scenario) return;
    const token = state.requestToken + 1;
    dispatch({ type: "predict-start", token });
    try { dispatch({ type: "predict-success", token, calculation: await api.predictModelDemo(scenario.id) }); }
    catch (error) { dispatch({ type: "failure", message: errorMessage(error) }); }
  };

  const publish = async () => {
    if (!state.calculation) return;
    dispatch({ type: "publish-start" });
    try {
      const result = await api.publishModelDemo(state.calculation.calculationId);
      dispatch({ type: "publish-success", alertId: result.alertId });
      await onRefresh();
      const destination = modelDemoPublicationPath(role, result.alertId);
      if (destination) navigate(destination);
    } catch (error) { dispatch({ type: "failure", message: errorMessage(error) }); }
  };

  const clear = async () => {
    if (typeof window !== "undefined" && !window.confirm("Удалить все результаты демонстрации, созданные предупреждения, заявки и SMS?")) return;
    dispatch({ type: "clear-start" });
    try { await api.clearModelDemoResults(); dispatch({ type: "clear-success" }); await onRefresh(); }
    catch (error) { dispatch({ type: "failure", message: errorMessage(error) }); }
  };

  const dangerous = state.calculation ? canPublishModelDemo(state.calculation.prediction.decisions) : undefined;
  const channelSummary = scenario?.sensors.length
    ? `${scenario.sensors.length} ${scenario.sensors.length === 1 ? "канал" : "каналов"}: ${scenario.sensors.slice(0, 2).map(sensorDisplayName).join(", ")}`
    : "Каналы не указаны";

  return <>
    <PageTitle title="Демонстрация модели" subtitle="24 записи отложенной выборки 2026 года" />
    {state.error && <p className="notice warning">{state.error}</p>}
    {!scenario ? <section className="panel"><div className="empty">{state.busy === "loading" ? "Загрузка тестовых показаний…" : "Тестовые показания недоступны."}</div></section> : <>
      <section className="panel model-demo-source">
        <div className="panel-head"><div><h2>Проверка обученной модели</h2><p>Расчёт риска для объекта</p></div><div className="model-demo-record">{dangerous !== undefined && <span className={`model-demo-example ${dangerous ? "danger" : "safe"}`}>{dangerous ? "Тревожный пример" : "Штатный пример"}</span>}<span className="model-demo-counter">Запись {state.index + 1} из {state.scenarios.length}</span></div></div>
        <dl className="facts model-demo-summary"><div><dt>Сценарий</dt><dd>{modelDemoScenarioLabel(scenario.inputs)}</dd></div><div><dt>Объект</dt><dd>{scenario.objectName}</dd></div><div><dt>Контрольные каналы</dt><dd>{channelSummary}</dd></div><div><dt>Время показаний</dt><dd>{formatDate(scenario.sourceTimestamp)}</dd></div><div className="model-demo-employees"><dt>Закреплённые сотрудники</dt><dd>{scenario.assignedEmployees?.length ? scenario.assignedEmployees.map((employee) => <span key={employee.id}><b>{employee.name}</b><small>{employee.role}</small></span>) : "Не назначены"}</dd></div></dl>
        <div className="model-demo-actions"><button className="secondary" disabled={!!state.busy} onClick={() => dispatch({ type: "next" })}>Следующие показания</button><button className="primary" disabled={!!state.busy} onClick={predict}>{state.busy === "predicting" ? "Расчёт…" : "Рассчитать прогноз"}</button><button className="danger-outline" disabled={!!state.busy} onClick={clear}>Очистить результаты демонстрации</button></div>
      </section>
      <div className="model-demo-layout">
        <section className="panel model-demo-input"><div className="panel-head"><div><h2>Входные данные</h2><p>{scenario.district} · {scenario.dangerousSection}</p></div></div><div className="model-demo-sensors">{scenario.sensors.map((sensor) => <article key={sensor.id} className={`model-demo-sensor ${sensor.state}`}><div><b>{sensorDisplayName(sensor)}</b><small>{sensor.picket ?? "Пикет не указан"}</small>{sensor.lastSeenAt && <small>Последнее измерение: {formatDate(sensor.lastSeenAt)}</small>}</div><div className="model-demo-reading"><span className={`sensor-state ${sensor.state}${/[A-Za-zА-Яа-яЁё]/.test(sensor.value) ? " text-value" : ""}`}>{sensor.value}</span></div></article>)}</div></section>
        <section className="panel model-demo-result"><div className="panel-head"><div><h2>Результат прогноза</h2>{state.calculation && <p>Рассчитано {formatDate(state.calculation.prediction.calculatedAt)}</p>}</div></div>{state.calculation ? <><div className="model-demo-probabilities">{[["Сейчас", state.calculation.prediction.pNow], ["6 часов", state.calculation.prediction.p6h], ["12 часов", state.calculation.prediction.p12h], ["24 часа", state.calculation.prediction.p24h]].map(([label, value]) => <div key={String(label)}><span>{label}</span><strong>{percent(value as number)}</strong></div>)}</div><div className="model-demo-actions"><button className="primary" disabled={!!state.busy || !!state.alertId || !canPublishModelDemo(state.calculation.prediction.decisions)} onClick={publish}>{state.alertId ? "Передано диспетчеру" : state.busy === "publishing" ? "Передача…" : "Передать диспетчеру"}</button>{state.alertId && (role === "district_dispatcher" || role === "ods_dispatcher") && <button className="secondary" onClick={() => navigate(`/alerts/${state.alertId}`)}>Открыть предупреждение</button>}</div>{!canPublishModelDemo(state.calculation.prediction.decisions) && <p className="muted model-demo-hint">Порог предупреждения не превышен. Передача диспетчеру не требуется.</p>}</> : <div className="model-demo-empty">Нажмите «Рассчитать прогноз»</div>}</section>
      </div>
    </>}
  </>;
}
