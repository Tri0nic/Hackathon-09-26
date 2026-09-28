create table if not exists infrastructure_objects (
    id text primary key,
    name text not null,
    district text not null default 'Не указан'
);

alter table infrastructure_objects add column if not exists district text not null default 'Не указан';

create table if not exists data_channels (
    id text primary key,
    object_id text not null references infrastructure_objects(id),
    sensor_type text not null,
    name text not null,
    picket_raw text,
    picket_sort_key double precision,
    display_value text,
    display_state text not null default 'normal',
    device_age_years double precision,
    age_source text not null default 'generated_demo',
    maintenance_note text,
    metadata_source text not null default 'demo'
);

alter table data_channels add column if not exists display_value text;
alter table data_channels add column if not exists display_state text not null default 'normal';
alter table data_channels add column if not exists age_source text not null default 'generated_demo';

create table if not exists risk_alerts (
    id uuid primary key,
    episode_id text not null,
    object_id text not null references infrastructure_objects(id),
    level text not null,
    horizon text not null,
    probability double precision not null check (probability between 0 and 1),
    p_now double precision not null,
    p_6h double precision not null,
    p_12h double precision not null,
    p_24h double precision not null,
    calculated_at timestamptz not null,
    model_version text not null,
    stale boolean not null default false,
    factors jsonb not null default '[]'::jsonb,
    recommendation text not null,
    alert_kind text not null default 'fire',
    context text not null default 'Данные не предоставлены',
    current boolean not null default true
);

alter table risk_alerts add column if not exists alert_kind text not null default 'fire';
alter table risk_alerts add column if not exists context text not null default 'Данные не предоставлены';

create table if not exists risk_predictions (
    id uuid primary key,
    object_id text not null references infrastructure_objects(id),
    model_version text not null,
    calculated_at timestamptz not null,
    p_now double precision not null,
    p_6h double precision not null,
    p_12h double precision not null,
    p_24h double precision not null,
    factors jsonb not null default '[]'::jsonb
);

create index if not exists ix_predictions_object_time
    on risk_predictions(object_id, calculated_at desc);

create table if not exists alert_level_history (
    id bigserial primary key,
    alert_id uuid not null references risk_alerts(id),
    from_level text,
    to_level text not null,
    changed_at timestamptz not null
);

create table if not exists dispatcher_decisions (
    id uuid primary key,
    alert_id uuid not null references risk_alerts(id),
    episode_id text not null,
    object_id text not null,
    decision text not null,
    comment text,
    decided_at timestamptz not null
);

create table if not exists maintenance_requests (
    id uuid primary key,
    alert_id uuid not null references risk_alerts(id),
    object_id text not null,
    picket text,
    factors jsonb not null,
    recommendation text not null,
    status text not null,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

alter table maintenance_requests add column if not exists request_kind text not null default 'inspection';
alter table maintenance_requests add column if not exists executor_group text not null default 'technician';
alter table maintenance_requests add column if not exists priority text not null default 'normal';
alter table maintenance_requests add column if not exists description text not null default 'Провести проверку объекта';
alter table maintenance_requests add column if not exists due_at timestamptz;
alter table maintenance_requests add column if not exists comment text;
alter table maintenance_requests add column if not exists creator_role text not null default 'district_dispatcher';
alter table maintenance_requests add column if not exists assignee_id text;
alter table maintenance_requests add column if not exists assignee_name text;

create table if not exists request_comments (
    id uuid primary key,
    request_id uuid not null references maintenance_requests(id) on delete cascade,
    employee_id text not null,
    employee_name text not null,
    comment_text text not null,
    created_at timestamptz not null
);

create index if not exists ix_request_comments_request_time
    on request_comments(request_id, created_at);

create table if not exists sms_notifications (
    id uuid primary key,
    episode_id text not null,
    alert_level text not null,
    recipient_id text not null,
    role text not null,
    sent_at timestamptz not null,
    content text not null,
    status text not null
);

alter table sms_notifications add column if not exists assignee_name text;
alter table sms_notifications add column if not exists processing_status text not null default 'waiting';
alter table sms_notifications alter column processing_status set default 'new';
update sms_notifications set processing_status='new' where processing_status='waiting' and status='delivered';
alter table sms_notifications add column if not exists recipient_name text;
alter table sms_notifications add column if not exists request_id uuid references maintenance_requests(id);

create index if not exists ix_sms_dedup
    on sms_notifications(episode_id, alert_level, recipient_id, sent_at desc);

insert into infrastructure_objects(id, name, district) values
    ('demo-object-1', 'Коллектор №1 · участок Северный', 'САО'),
    ('demo-object-2', 'Коллектор №4 · участок Восточный', 'ВАО'),
    ('demo-object-3', 'Коллектор №7 · участок Центральный', 'ЦАО'),
    ('demo-object-4', 'Коллектор №9 · участок Южный', 'ЮАО')
on conflict (id) do update set name=excluded.name, district=excluded.district;

insert into data_channels(id, object_id, sensor_type, name, picket_raw, picket_sort_key,
    display_value, display_state, device_age_years, age_source, maintenance_note, metadata_source) values
    ('demo-temp-1', 'demo-object-1', 'Температура', 'Температура ПК 12+50', '12+50', 12.5, '68 °C', 'danger', 4.2, 'generated_demo', 'ТО 15.08.2026', 'demo'),
    ('demo-smoke-1', 'demo-object-1', 'Дым', 'Дым ПК 12+70', '12+70', 12.7, 'Обнаружен дым', 'danger', 3.5, 'generated_demo', 'ТО 20.07.2026', 'demo'),
    ('demo-gas-1', 'demo-object-1', 'Газ', 'Газ ПК 12+90', '12+90', 12.9, '0,7%', 'warning', 5.1, 'first_seen', 'ТО 02.06.2026', 'computed'),
    ('demo-service-1', 'demo-object-1', 'Диагностика', 'Служебный канал без пикета', null, null, 'Нет связи', 'malfunction', 2.0, 'generated_demo', 'Данные не предоставлены', 'demo'),
    ('demo-service-2', 'demo-object-2', 'Диагностика', 'Канал связи без пикета', null, null, 'Нет связи', 'malfunction', 2.8, 'generated_demo', 'Данные не предоставлены', 'demo'),
    ('demo-temp-3', 'demo-object-3', 'Температура', 'Температура ПК 08+20', '08+20', 8.2, '31 °C', 'normal', 4.0, 'first_seen', 'ТО 10.07.2026', 'computed'),
    ('demo-smoke-4', 'demo-object-4', 'Дым', 'Дым ПК 03+10', '03+10', 3.1, 'Тревога', 'danger', 3.1, 'generated_demo', 'ТО 01.09.2026', 'demo')
on conflict (id) do update set display_value=excluded.display_value, display_state=excluded.display_state;

insert into risk_alerts(id, episode_id, object_id, level, horizon, probability, p_now, p_6h, p_12h, p_24h,
    calculated_at, model_version, stale, factors, recommendation, alert_kind, context, current) values
    ('11111111-1111-1111-1111-111111111111', 'EP-DEMO-MAIN', 'demo-object-1', 'red', '6h', 0.82, 0.18, 0.82, 0.88, 0.93,
     '2026-09-27T12:42:00+03:00', 'catboost-e87d5604945b', false,
     '[{"label":"Рост температуры","contribution":0.34,"detail":"+29 °C к суточному профилю"},{"label":"Сигнал дыма","contribution":0.28,"detail":"3 срабатывания за 15 минут"}]',
     'Проверить участок ПК 12+50–12+90 и состояние пожарных датчиков.', 'fire',
     'Демонстрационный контекст из отдельного mock-источника: рядом запланированы сварочные работы.', true),
    ('22222222-2222-2222-2222-222222222222', 'EP-DEMO-FAULT', 'demo-object-2', 'yellow', '12h', 0.67, 0.09, 0.38, 0.67, 0.72,
     '2026-09-27T12:31:00+03:00', 'catboost-e87d5604945b', false,
     '[{"label":"Потеря связи","contribution":0.44,"detail":"Нет данных 47 минут"}]',
     'Проверить питание и линию связи датчика.', 'malfunction', 'Данные о работах не предоставлены.', true),
    ('33333333-3333-3333-3333-333333333333', 'EP-DEMO-GREEN', 'demo-object-3', 'green', '24h', 0.41, 0.03, 0.14, 0.25, 0.41,
     '2026-09-27T12:14:00+03:00', 'catboost-e87d5604945b', false,
     '[{"label":"Температурный тренд","contribution":0.18,"detail":"+6 °C за 3 часа"}]',
     'Продолжить наблюдение.', 'fire', 'Данные о работах не предоставлены.', true),
    ('44444444-4444-4444-4444-444444444444', 'EP-DEMO-BLACK', 'demo-object-4', 'black', 'now', 0.91, 0.91, 0.94, 0.96, 0.98,
     '2026-09-27T12:48:00+03:00', 'catboost-e87d5604945b', false,
     '[{"label":"Дым и быстрый нагрев","contribution":0.61,"detail":"Совместный пожарный паттерн"}]',
     'Немедленно проверить участок и направить группу реагирования.', 'fire', 'Демонстрационный сценарий BLACK.', true)
on conflict (id) do nothing;

insert into alert_level_history(alert_id, from_level, to_level, changed_at)
select '11111111-1111-1111-1111-111111111111', x.from_level, x.to_level, x.changed_at
from (values
    (null::text, 'green', '2026-09-27T11:30:00+03:00'::timestamptz),
    ('green', 'yellow', '2026-09-27T11:50:00+03:00'::timestamptz),
    ('yellow', 'red', '2026-09-27T12:10:00+03:00'::timestamptz),
    ('red', 'black', '2026-09-27T12:30:00+03:00'::timestamptz),
    ('black', 'red', '2026-09-27T12:42:00+03:00'::timestamptz)
) x(from_level, to_level, changed_at)
where not exists (select 1 from alert_level_history where alert_id='11111111-1111-1111-1111-111111111111');

insert into risk_predictions(id, object_id, model_version, calculated_at, p_now, p_6h, p_12h, p_24h, factors) values
    ('55555555-5555-5555-5555-555555555555', 'demo-object-1', 'catboost-e87d5604945b', '2026-09-27T12:42:00+03:00', 0.18, 0.82, 0.88, 0.93, '[]')
on conflict (id) do nothing;

insert into dispatcher_decisions(id, alert_id, episode_id, object_id, decision, comment, decided_at) values
    ('66666666-6666-6666-6666-666666666666', '33333333-3333-3333-3333-333333333333', 'EP-DEMO-GREEN', 'demo-object-3', 'maintenance', 'Продолжить наблюдение', '2026-09-27T12:18:00+03:00')
on conflict (id) do nothing;

insert into maintenance_requests(id, alert_id, object_id, picket, factors, recommendation, status, created_at, updated_at) values
    ('77777777-7777-7777-7777-777777777777', '33333333-3333-3333-3333-333333333333', 'demo-object-3', '08+20', '[]', 'Проверить температурный датчик', 'scheduled', '2026-09-27T12:20:00+03:00', '2026-09-27T12:24:00+03:00')
on conflict (id) do nothing;

insert into sms_notifications(id, episode_id, alert_level, recipient_id, role, sent_at, content, status)
select md5('EP-DEMO-MAIN|' || level || '|' || role || '|' || sent_at::text)::uuid,
       'EP-DEMO-MAIN', level, role, role, sent_at,
       case when note='deescalation' then 'Деэскалация BLACK → RED' else 'Демонстрационное уведомление: уровень ' || upper(level) end,
       'delivered'
from (values
    ('green','OdsDispatcher','2026-09-27T11:30:00+03:00'::timestamptz,'level'),
    ('yellow','DistrictDispatcher','2026-09-27T11:50:00+03:00'::timestamptz,'level'),
    ('yellow','OdsDispatcher','2026-09-27T11:50:00+03:00'::timestamptz,'level'),
    ('red','Technician','2026-09-27T12:10:00+03:00'::timestamptz,'level'),
    ('red','DistrictDispatcher','2026-09-27T12:10:00+03:00'::timestamptz,'level'),
    ('red','OdsDispatcher','2026-09-27T12:10:00+03:00'::timestamptz,'level'),
    ('black','Technician','2026-09-27T12:30:00+03:00'::timestamptz,'level'),
    ('black','DistrictDispatcher','2026-09-27T12:30:00+03:00'::timestamptz,'level'),
    ('black','OdsDispatcher','2026-09-27T12:30:00+03:00'::timestamptz,'level'),
    ('black','ResponseTeam','2026-09-27T12:30:00+03:00'::timestamptz,'level'),
    ('red','Technician','2026-09-27T12:42:00+03:00'::timestamptz,'deescalation'),
    ('red','DistrictDispatcher','2026-09-27T12:42:00+03:00'::timestamptz,'deescalation'),
    ('red','OdsDispatcher','2026-09-27T12:42:00+03:00'::timestamptz,'deescalation')
) x(level, role, sent_at, note)
on conflict (id) do nothing;

update sms_notifications
set assignee_name = 'Илья Сергеевич Иванов',
    processing_status = 'in_progress',
    status = 'delivered'
where episode_id = 'EP-DEMO-MAIN';

insert into sms_notifications(id, episode_id, alert_level, recipient_id, role, sent_at, content, status, assignee_name, processing_status)
values
    (md5('EP-DEMO-FAULT|yellow|OdsDispatcher')::uuid, 'EP-DEMO-FAULT', 'yellow', 'OdsDispatcher', 'OdsDispatcher', '2026-09-27T12:31:04+03:00', 'Технический сбой: потеря связи с каналом на Восточном участке', 'delivered', 'Наталья Викторовна Орлова', 'in_progress'),
    (md5('EP-DEMO-GREEN|green|OdsDispatcher')::uuid, 'EP-DEMO-GREEN', 'green', 'OdsDispatcher', 'OdsDispatcher', '2026-09-27T12:14:05+03:00', 'Зелёный уровень: продолжить наблюдение за температурным трендом', 'delivered', 'Мария Андреевна Петрова', 'completed'),
    (md5('EP-DEMO-BLACK|black|ResponseTeam')::uuid, 'EP-DEMO-BLACK', 'black', 'ResponseTeam', 'ResponseTeam', '2026-09-27T12:48:05+03:00', 'Чёрный уровень: немедленно проверить задымление на Южном участке', 'failed', null, 'undelivered')
on conflict (id) do update set
    content = excluded.content,
    status = excluded.status,
    assignee_name = excluded.assignee_name,
    processing_status = excluded.processing_status;

update sms_notifications
set status = 'delivered',
    processing_status = case when processing_status in ('completed', 'in_progress') then processing_status else 'in_progress' end
where id <> md5('EP-DEMO-BLACK|black|ResponseTeam')::uuid;

update sms_notifications
set status = 'failed', assignee_name = null, processing_status = 'undelivered'
where id = md5('EP-DEMO-BLACK|black|ResponseTeam')::uuid;

-- The current notification contract starts at request creation. Remove legacy
-- risk-level demo messages and seed one notification per target employee.
delete from sms_notifications where request_id is null;

insert into sms_notifications(
    id, episode_id, alert_level, recipient_id, recipient_name, role, request_id,
    sent_at, content, status, assignee_name, processing_status)
values
    (md5('REQ-DEMO|tech-ivanov')::uuid, 'EP-DEMO-GREEN', 'green', 'tech-ivanov', 'Илья Сергеевич Иванов', 'Technician',
     '77777777-7777-7777-7777-777777777777', '2026-09-27T12:20:03+03:00', 'Создана заявка: проверить температурный датчик', 'delivered', null, 'new'),
    (md5('REQ-DEMO|tech-petrova')::uuid, 'EP-DEMO-GREEN', 'green', 'tech-petrova', 'Мария Андреевна Петрова', 'Technician',
     '77777777-7777-7777-7777-777777777777', '2026-09-27T12:20:04+03:00', 'Создана заявка: проверить температурный датчик', 'delivered', null, 'new'),
    (md5('REQ-DEMO|tech-sokolov')::uuid, 'EP-DEMO-GREEN', 'green', 'tech-sokolov', 'Алексей Дмитриевич Соколов', 'Technician',
     '77777777-7777-7777-7777-777777777777', '2026-09-27T12:20:05+03:00', 'Создана заявка: проверить температурный датчик', 'failed', null, 'undelivered')
on conflict (id) do nothing;

update sms_notifications s
set processing_status='new', assignee_name=null
from maintenance_requests r
where s.request_id=r.id and s.status='delivered' and r.assignee_id is null
  and r.status not in ('completed','rejected');
