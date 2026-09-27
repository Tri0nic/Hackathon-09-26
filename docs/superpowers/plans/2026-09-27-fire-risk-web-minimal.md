# Fire Risk WEB Minimal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Создать компактный демонстрационный WEB-интерфейс пожарных рисков, покрывающий WEB-01…WEB-06.

**Architecture:** Один Vite SPA в `services/web`, общий shell и маршрутизация без отдельного router-пакета. Данные идут через существующий API либо явно обозначенный demo-fixture; карта и графики — собственные SVG.

**Tech Stack:** React, TypeScript, Vite, Vitest, CSS, SVG.

**Spec:** `docs/superpowers/specs/2026-09-27-fire-risk-web-minimal-design.md`

## Global Constraints

- Интерфейс на русском языке, desktop-first.
- Следовать корневому `DESIGN.md`.
- Цвет не является единственным носителем уровня риска.
- Demo/mock-поля имеют видимую маркировку.
- Не добавлять UI- и chart-библиотеки.

## Review Focus

- BLACK/RED/YELLOW/GREEN имеют правильные русские названия горизонтов.
- Технический сбой не называется пожаром.
- Каналы без пикета остаются видимыми.
- Ошибка API переводит demo-режим в понятное состояние, а не ломает экран.
- Действия решения и заявки дают пользователю видимую обратную связь.

---

### Task 1: Каркас данных и критичные правила

**Files:**
- Create: `services/web/package.json`
- Create: `services/web/src/types.ts`
- Create: `services/web/src/domain.ts`
- Create: `services/web/src/domain.test.ts`
- Create: `services/web/src/demo.ts`
- Create: `services/web/src/api.ts`

**Interfaces:**
- Produces: `riskLabel(level)`, `alertKindLabel(kind)`, `splitPickets(channels)` и `api`.

- [ ] Написать три падающих теста для горизонтов, технического сбоя и группы без пикета.
- [ ] Запустить `npm test -- --run` и подтвердить ожидаемое падение.
- [ ] Реализовать минимальные типы, правила, demo-fixture и API-клиент.
- [ ] Запустить `npm test -- --run` и получить PASS.

### Task 2: Интерфейс WEB-01…WEB-06

**Files:**
- Create: `services/web/index.html`
- Create: `services/web/src/main.tsx`
- Create: `services/web/src/App.tsx`
- Create: `services/web/src/components.tsx`
- Create: `services/web/src/styles.css`
- Create: `services/web/README.md`

**Interfaces:**
- Consumes: типы, правила, demo-fixture и `api` из Task 1.
- Produces: маршруты Dashboard, объекты/карта, предупреждения, заявки, аналитика и SMS.

- [ ] Собрать shell, навигацию и все шесть экранов в одном компактном компонентном наборе.
- [ ] Реализовать SVG-карту, график вероятностей, полную карточку и формы действий.
- [ ] Добавить адаптивное поведение для узкого desktop/tablet.
- [ ] Выполнить `npm test -- --run`, `npm run typecheck` и `npm run build`.
