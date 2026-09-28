import { useEffect, useReducer } from "react";
import { api } from "./api";
import { PageTitle } from "./components";
import { formatDate } from "./domain";
import { canPublishModelDemo, initialModelDemoState, modelDemoReducer, modelFactorLabel } from "./modelDemo";
import type { ModelDemoState } from "./modelDemo";
import type { UserRole } from "./types";

const percent = (value: number) => `${Math.round(value * 100)}%`;
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "Не удалось выполнить операцию";

export function ModelDemoPage({ navigate, onRefresh, role, initialState }: { navigate: (path: string) => void; onRefresh: () => Promise<void>; role: UserRole; initialState?: ModelDemoState }) {
  const [state, dispatch] = useReducer(modelDemoReducer, initialState ?? initialModelDemoState);
  const scenario = state.scenarios[state.index];

  useEffect(() => {
    if (initialState) return;
    api.listModelDemoScenarios().then((scenarios) => dispatch({ type: "load-success", scenarios })).catch((error) => dispatch({ type: "failure", message: errorMessage(error) }));
  }, [initialState]);

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
    } catch (error) { dispatch({ type: "failure", message: errorMessage(error) }); }
  };

  const clear = async () => {
    if (typeof window !== "undefined" && !window.confirm("Удалить все результаты демонстрации, созданные предупреждения, заявки и SMS?")) return;
    dispatch({ type: "clear-start" });
    try { await api.clearModelDemoResults(); dispatch({ type: "clear-success" }); await onRefresh(); }
    catch (error) { dispatch({ type: "failure", message: errorMessage(error) }); }
  };

  return <>
    <PageTitle title="Демонстрация модели" subtitle="Расчёт на последовательных записях отложенной выборки 2026 года"><span className="demo-badge">Демо</span></PageTitle>
    <p className="notice info">Показания взяты из тестовой выборки и не редактируются вручную. Расчёт не переключает запись; для перехода используйте кнопку «Следующие показания».</p>
    {state.error && <p className="notice warning">{state.error}</p>}
    {!scenario ? <section className="panel"><div className="empty">{state.busy === "loading" ? "Загрузка тестовых показаний…" : "Тестовые показания недоступны."}</div></section> : <>
      <section className="panel model-demo-source">
        <div className="panel-head"><div><h2>{scenario.objectName}</h2><p>{scenario.district} · {scenario.dangerousSection}</p></div><div className="model-demo-counter">Запись {state.index + 1} из {state.scenarios.length}</div></div>
        <dl className="facts"><div><dt>Время показаний</dt><dd>{formatDate(scenario.sourceTimestamp)}</dd></div><div><dt>Идентификатор объекта в выборке</dt><dd>{scenario.objectId}</dd></div></dl>
        <div className="model-demo-sensors">{scenario.sensors.map((sensor) => <article key={sensor.id}><div><b>{sensor.name}</b><small>{sensor.picket ?? "Пикет не указан"}</small></div><span className={`sensor-state ${sensor.state}`}>{sensor.value}</span></article>)}</div>
        <div className="model-demo-actions"><button className="secondary" disabled={!!state.busy} onClick={() => dispatch({ type: "next" })}>Следующие показания</button><button className="primary" disabled={!!state.busy} onClick={predict}>{state.busy === "predicting" ? "Расчёт…" : "Рассчитать прогноз"}</button><button className="danger-outline" disabled={!!state.busy} onClick={clear}>Очистить результаты демонстрации</button></div>
      </section>
      {state.calculation && <section className="panel model-demo-result">
        <div className="panel-head"><div><h2>Результат прогноза</h2><p>Рассчитано {formatDate(state.calculation.prediction.calculatedAt)}</p></div></div>
        <div className="model-demo-probabilities">{[["Сейчас", state.calculation.prediction.pNow], ["6 часов", state.calculation.prediction.p6h], ["12 часов", state.calculation.prediction.p12h], ["24 часа", state.calculation.prediction.p24h]].map(([label, value]) => <div key={String(label)}><span>{label}</span><strong>{percent(value as number)}</strong></div>)}</div>
        <div className="model-demo-factors"><h3>Основные факторы</h3>{state.calculation.prediction.factors.slice(0, 5).map((factor, index) => <div key={`${factor.horizon}-${factor.feature}-${index}`}><b>{modelFactorLabel(factor.feature)}</b><span>{factor.contribution >= 0 ? "+" : ""}{factor.contribution.toFixed(3)}</span></div>)}</div>
        <div className="model-demo-actions"><button className="primary" disabled={!!state.busy || !!state.alertId || !canPublishModelDemo(state.calculation.prediction.decisions)} onClick={publish}>{state.alertId ? "Передано диспетчеру" : state.busy === "publishing" ? "Передача…" : "Передать диспетчеру"}</button>{state.alertId && (role === "district_dispatcher" || role === "ods_dispatcher") && <button className="secondary" onClick={() => navigate(`/alerts/${state.alertId}`)}>Открыть предупреждение</button>}</div>
        {!canPublishModelDemo(state.calculation.prediction.decisions) && <p className="muted model-demo-hint">Порог предупреждения не превышен — передача диспетчеру не требуется.</p>}
      </section>}
    </>}
  </>;
}
