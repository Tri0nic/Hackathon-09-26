# Role Workspaces and Request Dispatch Design

## Goal

Make the selected role materially change the workspace, let dispatchers create complete work requests from an alert, notify every member of the selected executor group when the request is created, and let the first executor claim the request.

## Roles and navigation

- District dispatcher: overview, district objects, alerts, requests, SMS. Can create regular or emergency requests.
- ODS dispatcher: system-wide overview, objects, alerts, requests, analytics, SMS. Can create emergency requests only; executor is fixed to the response team.
- Technician: available technician requests, own requests, related objects, and SMS. Cannot create requests or use analytics.
- Response team: available emergency response requests, own requests, related critical objects, and SMS. Cannot create requests or use analytics.
- Selecting technician or response-team role also requires selecting a demo employee. That employee identity is used when claiming a request.

## Request creation

The alert details page opens a dedicated request form instead of creating immediately. The form carries the alert and object context and contains request type, executor group, priority, description, due date, and comment. District dispatchers can choose technicians or response team. ODS dispatchers see a fixed emergency request assigned to the response team.

## Notification and claiming rules

- SMS is generated only when a request is created, not when a prediction changes alert level.
- Every active employee in the selected executor group receives a separate SMS record.
- A claim assigns the request to the first employee whose atomic server update succeeds and moves it to `in_progress`.
- A later claimant receives a conflict response and the UI refreshes to show the current assignee.
- SMS processing state follows the request: delivered notifications begin `new` («Свободная заявка»), claiming changes them to `in_progress`, failed notifications remain `undelivered`, and completed requests mark delivered notifications `completed`.

## Data model

Requests store executor group, request type, priority, description, due date, comment, creator role, assignee ID, and assignee name. SMS records store the related request ID and employee recipient. Demo mode mirrors the same contracts in memory.

## Compatibility

Analytics stays available to ODS because model-quality characteristics are required by the product requirements. Existing request status transitions remain available to dispatchers; executors use the dedicated claim action. The sidebar system/model footer is removed.

## Acceptance criteria

- Switching roles changes visible navigation and allowed actions.
- Technician and response-team roles require an employee selection.
- Request creation opens and validates a form.
- ODS can create only emergency response-team requests.
- Creation adds one SMS per member of the selected group.
- Risk-level changes do not add SMS.
- Only the first employee can claim an unassigned request.
- Request lists distinguish available and own work for executors.

