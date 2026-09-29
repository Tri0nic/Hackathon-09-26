# Krot Kolya Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить на сайт анимированного крота и локальный контекстный чат.

**Architecture:** React-компонент отображает CSS-спрайт и управляет состояниями. Чистая функция ранжирует локальные записи базы знаний по словам запроса и текущему пути.

**Tech Stack:** React, TypeScript, CSS, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-29-krot-kolya-assistant.md`

## Global Constraints

- Без ИИ, backend-запросов и новых зависимостей.
- По умолчанию питомец стоит и моргает.
- Использовать существующий спрайт Кота Коли.

## Review Focus

- Пустой запрос не должен давать случайный ответ.
- Неизвестный вопрос должен возвращать понятный fallback.
- Контекст текущего раздела должен влиять на подсказку.
- Таймеры реакции должны очищаться.
- Виджет не должен перекрывать мобильную навигацию.

---

### Task 1: Локальный поиск ответов

**Files:**
- Create: `services/web/src/petKnowledge.ts`
- Test: `services/web/src/petKnowledge.test.ts`

**Interfaces:**
- Produces: `answerPetQuestion(query: string, path: string): PetAnswer`

- [ ] Написать тесты найденного ответа, контекстной подсказки и fallback.
- [ ] Запустить тест и увидеть ожидаемое падение из-за отсутствующего модуля.
- [ ] Реализовать минимальный ранжировщик по токенам.
- [ ] Запустить тесты до зелёного результата.

### Task 2: Виджет, анимации и интеграция

**Files:**
- Create: `services/web/src/PetAssistant.tsx`
- Create: `services/web/src/assets/krot-kolya.png`
- Modify: `services/web/src/App.tsx`
- Modify: `services/web/src/App.test.tsx`
- Modify: `services/web/src/styles.css`

**Interfaces:**
- Consumes: `answerPetQuestion(query, path)`
- Produces: `PetAssistant({ path })`

- [ ] Добавить серверный тест присутствия виджета в приложении и увидеть его падение.
- [ ] Реализовать спрайтовую анимацию и чат.
- [ ] Подключить компонент к корню приложения и добавить адаптивные стили.
- [ ] Запустить тесты и сборку.
