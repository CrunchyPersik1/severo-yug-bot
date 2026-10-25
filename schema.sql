-- Схема БД «Северо-Юг» (PostgreSQL / Supabase).
-- Применяется автоматически при старте приложения (idempotent).

create table if not exists cards (
    card_id       text primary key,
    name          text not null,
    rarity        text not null,
    points        integer not null,
    hp            integer not null,
    atk           integer not null,
    ability_name  text not null,
    ability_cd    integer not null,
    ability       jsonb  not null,
    image_file_id text
);

create table if not exists players (
    user_id       bigint primary key,
    username      text,
    first_name    text,
    last_drop_day date,
    wins          integer not null default 0,
    losses        integer not null default 0,
    draws         integer not null default 0,
    kills         integer not null default 0,   -- сколько чужих карт убито
    bonus_points  integer not null default 0,   -- очки, отжатые/отданные в PvP
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

create table if not exists collection (
    user_id   bigint not null references players(user_id) on delete cascade,
    card_id   text   not null references cards(card_id),
    count     integer not null default 1,
    kills     integer not null default 0,       -- убийства этой конкретной карты
    first_at  timestamptz not null default now(),
    primary key (user_id, card_id)
);
create index if not exists collection_card_idx on collection (card_id);

create table if not exists drops (
    id        bigserial primary key,
    user_id   bigint not null,
    chat_id   bigint,
    card_id   text not null,
    day_key   date not null,
    rolled_at timestamptz not null default now()
);
create index if not exists drops_user_day_idx on drops (user_id, day_key);

create table if not exists battles (
    battle_id    text primary key,
    chat_id      bigint not null,
    message_id   bigint,
    challenger_id bigint not null,
    opponent_id  bigint,
    status       text not null default 'choosing',   -- choosing | active | finished
    state        jsonb not null,
    turn_no      integer not null default 0,
    winner_id    bigint,
    version      integer not null default 0,
    pick_a_chat  bigint,
    pick_a_msg   bigint,
    pick_b_chat  bigint,
    pick_b_msg   bigint,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);
create index if not exists battles_chat_status_idx on battles (chat_id, status);
create index if not exists battles_status_updated_idx on battles (status, updated_at);
create index if not exists battles_challenger_idx on battles (challenger_id, status);
create index if not exists battles_opponent_idx on battles (opponent_id, status);
-- миграции для баз, созданных до появления PvP-наград
alter table players    add column if not exists kills        integer not null default 0;
alter table players    add column if not exists bonus_points integer not null default 0;
alter table players    add column if not exists favorite_card text;
alter table players    add column if not exists xp             integer not null default 0;
alter table players    add column if not exists rewarded_level integer not null default 1;
alter table collection add column if not exists kills        integer not null default 0;
-- ===================================================================== --
-- Рынок, инвентарь и улучшения
-- ===================================================================== --

-- Уникальная копия карты. Дубликаты БЕЗ улучшений живут стаком в collection,
-- а как только карту улучшили — она переезжает сюда и получает свой id.
create table if not exists inventory (
    id         bigserial primary key,
    user_id    bigint not null references players(user_id) on delete cascade,
    card_id    text   not null references cards(card_id),
    listed     boolean not null default false,
    created_at timestamptz not null default now()
);
create index if not exists inventory_user_idx on inventory (user_id, listed);

create table if not exists auras (
    id         serial primary key,
    name       text not null unique,
    stat_bonus jsonb not null
);

create table if not exists backgrounds (
    id         serial primary key,
    name       text not null unique,
    stat_bonus jsonb not null
);

create table if not exists effects (
    id         serial primary key,
    name       text not null unique,
    stat_bonus jsonb not null
);

-- Улучшения привязаны к конкретной копии карты (inventory_id), а не к card_id.
-- Максимум одна аура, один фон и один эффект — значит одна строка на копию.
create table if not exists upgrades (
    id            bigserial primary key,
    inventory_id  bigint not null unique references inventory(id) on delete cascade,
    aura_id       int references auras(id),
    background_id int references backgrounds(id),
    effect_id     int references effects(id),
    created_at    timestamptz not null default now()
);

create table if not exists market (
    id           bigserial primary key,
    seller_id    bigint not null references players(user_id) on delete cascade,
    card_id      text   not null references cards(card_id),
    inventory_id bigint references inventory(id) on delete cascade,
    price        integer not null check (price >= 0),
    status       text not null default 'active',
    suspect      boolean not null default false,
    market_price integer not null default 0,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);
create index if not exists market_status_idx on market (status, created_at desc);
create index if not exists market_seller_idx on market (seller_id, status);

create table if not exists history (
    id        bigserial primary key,
    buyer_id  bigint not null,
    seller_id bigint not null,
    card_id   text not null,
    price     integer not null,
    fee       integer not null default 0,
    timestamp timestamptz not null default now()
);
create index if not exists history_buyer_idx on history (buyer_id, timestamp desc);

create table if not exists gifts (
    id           bigserial primary key,
    sender_id    bigint not null,
    receiver_id  bigint not null,
    card_id      text not null,
    inventory_id bigint,
    timestamp    timestamptz not null default now()
);

-- Репутация торговца. Старт 5.0, падает за демпинг, растёт за честные сделки.
alter table players add column if not exists rating       numeric(4,2) not null default 5.0;
alter table players add column if not exists rating_day   date;
alter table players add column if not exists rating_today numeric(4,2) not null default 0;
-- ===================================================================== --
-- Рулетка и кейсы
-- ===================================================================== --

-- Отдельный сброс рулетки: 20:00 по ЕКБ = 15:00 UTC (у «Северо-Юг» свой, в 07:00 UTC).
alter table players add column if not exists roulette_day date;

-- Кейс — самостоятельный предмет инвентаря, не карта.
create table if not exists cases (
    id         bigserial primary key,
    user_id    bigint not null references players(user_id) on delete cascade,
    opened     boolean not null default false,
    listed     boolean not null default false,
    source     text not null default 'roulette',
    created_at timestamptz not null default now()
);
create index if not exists cases_user_idx on cases (user_id, opened, listed);

-- Лот на рынке теперь может быть картой, улучшенной копией или кейсом.
alter table market  alter column card_id drop not null;
alter table market  add column if not exists kind    text   not null default 'card';
alter table market  add column if not exists case_id bigint references cases(id) on delete cascade;
alter table history alter column card_id drop not null;
alter table history add column if not exists kind text not null default 'card';
alter table gifts add column if not exists kind text not null default 'card';
alter table gifts alter column card_id drop not null;
-- Очки становятся единой валютой: баланс = то, что видно в /my и /profile.
-- Разовая досдача очков за карты, полученные до этого изменения.
alter table players add column if not exists points_backfilled boolean not null default false;

update players p
   set bonus_points = bonus_points + coalesce(sub.total, 0),
       points_backfilled = true
  from (
        select col.user_id, sum(c.points)::int as total
          from collection col
          join cards c on c.card_id = col.card_id
         group by col.user_id
       ) sub
 where sub.user_id = p.user_id
   and p.points_backfilled is false;

update players set points_backfilled = true where points_backfilled is false;
-- Фамилии для карт с повторяющимися именами (два Тамерлана, два Амира, два Данияра)
alter table cards add column if not exists surname text;
-- Попытки на сутки: сколько уже потрачено и сколько разрешено.
-- Лимит сбрасывается на дефолтный при смене дня, но его можно поднять разово
-- (акции, раздачи в честь обновления).
alter table players add column if not exists drop_uses     integer not null default 0;
alter table players add column if not exists drop_limit    integer not null default 1;
alter table players add column if not exists roulette_uses integer not null default 0;
alter table players add column if not exists roulette_limit integer not null default 1;
-- ===================================================================== --
-- Казино
-- ===================================================================== --

-- Бонусы (и штрафы), которые карта получила в казино. Складываются с бонусами
-- ауры/фона/эффекта и точно так же влияют на статы и цену.
alter table inventory add column if not exists casino_bonus jsonb not null default '{}'::jsonb;

-- Снимок проигранной карты: её можно выкупить, пока действует предложение.
create table if not exists casino_lost (
    id           bigserial primary key,
    user_id      bigint not null references players(user_id) on delete cascade,
    card_id      text not null,
    casino_bonus jsonb not null default '{}'::jsonb,
    upgrades     jsonb not null default '{}'::jsonb,
    price        integer not null,
    bought       boolean not null default false,
    created_at   timestamptz not null default now(),
    expires_at   timestamptz not null
);
create index if not exists casino_lost_user_idx on casino_lost (user_id, bought, expires_at);

create table if not exists casino_log (
    id         bigserial primary key,
    user_id    bigint not null,
    bet_kind   text not null,
    bet_value  text,
    color      text not null,
    rolled     text not null,
    won        boolean not null,
    outcome    text not null,
    amount     integer not null default 0,
    created_at timestamptz not null default now()
);
create index if not exists casino_log_user_idx on casino_log (user_id, created_at desc);
-- ===================================================================== --
-- Чаты с ботом (для админской рассылки в группы)
-- ===================================================================== --

create table if not exists chats (
    chat_id   bigint primary key,
    kind      text not null,
    title     text,
    added_at  timestamptz not null default now(),
    last_seen timestamptz not null default now(),
    left_at   timestamptz
);
create index if not exists chats_alive_idx on chats (kind) where left_at is null;
-- Бэкфилл: собираем группы, где бот уже играл, из прошлых боёв и дропов.
-- Лички (положительные id) сюда не попадают.
insert into chats (chat_id, kind)
select distinct chat_id, 'supergroup' from battles where chat_id < 0
on conflict (chat_id) do nothing;

insert into chats (chat_id, kind)
select distinct chat_id, 'supergroup' from drops where chat_id < 0
on conflict (chat_id) do nothing;
-- ===================================================================== --
-- Магазин и аксессуары
-- ===================================================================== --

-- Аксессуары (четвёртый слот улучшений) покупаются в магазине.
create table if not exists accessories (
    id         bigserial primary key,
    user_id    bigint not null references players(user_id) on delete cascade,
    item_id    integer not null,
    card_id    text,
    created_at timestamptz not null default now()
);
create index if not exists accessories_user_idx on accessories (user_id);

-- История покупок: чтобы видеть, кто и что брал.
create table if not exists shop_log (
    id         bigserial primary key,
    user_id    bigint not null,
    sku        text not null,
    price      integer not null,
    created_at timestamptz not null default now()
);
create index if not exists shop_log_user_idx on shop_log (user_id, created_at desc);

-- ===================================================================== --
-- Промокоды и лимит круток казино
-- ===================================================================== --

alter table players add column if not exists casino_day date;
alter table players add column if not exists casino_uses integer not null default 0;
alter table players add column if not exists casino_limit integer not null default 25;

create table if not exists promo_uses (
    user_id    bigint not null references players(user_id) on delete cascade,
    code       text not null,
    created_at timestamptz not null default now(),
    primary key (user_id, code)
);

-- ===================================================================== --
-- Реферальные ссылки
-- ===================================================================== --

-- Одна активная ссылка на игрока. Живёт, пока не наберёт max_uses человек;
-- новую можно создать только через 7 дней после прошлой.
create table if not exists ref_links (
    id         bigserial primary key,
    code       text not null unique,
    owner_id   bigint not null references players(user_id) on delete cascade,
    created_at timestamptz not null default now(),
    uses       integer not null default 0,
    max_uses   integer not null default 25,
    active     boolean not null default true
);
create index if not exists ref_links_owner_idx on ref_links (owner_id, created_at desc);

-- Один человек может быть приглашён только один раз за всё время.
create table if not exists referrals (
    referred_id bigint primary key,
    referrer_id bigint not null,
    link_id     bigint references ref_links(id) on delete set null,
    created_at  timestamptz not null default now()
);
create index if not exists referrals_referrer_idx on referrals (referrer_id);

-- ===================================================================== --
-- Биржа
-- ===================================================================== --

create table if not exists stocks (
    id         bigserial primary key,
    slug       text not null unique,
    name       text not null,
    emoji      text not null default '📈',
    base_price integer not null,
    price      integer not null,
    prev_price integer not null default 0,
    volatility numeric(6,4) not null default 0.03,
    updated_at timestamptz not null default now(),
    -- Последняя отметка, от которой считаем рост для оповещения (+10%).
    alert_price integer not null default 0,
    alerted_at  timestamptz,
    -- Цель админа: курс плавно едет к ней, потом цель сбрасывается.
    target_price integer,
    -- Внезапный памп: фаза 'up'/'down', вершина и цена возврата.
    pump_phase text,
    pump_peak  integer,
    pump_home  integer,
    pump_at    timestamptz
);

-- Миграции для баз, где stocks уже была создана без этих колонок.
alter table stocks add column if not exists alert_price integer not null default 0;
alter table stocks add column if not exists alerted_at  timestamptz;
alter table stocks add column if not exists target_price integer;
alter table stocks add column if not exists pump_phase text;
alter table stocks add column if not exists pump_peak  integer;
alter table stocks add column if not exists pump_home  integer;
alter table stocks add column if not exists pump_at    timestamptz;

-- История курса для графика (свечки-квадратики).
create table if not exists stock_history (
    id       bigserial primary key,
    stock_id bigint not null references stocks(id) on delete cascade,
    price    integer not null,
    at       timestamptz not null default now()
);
create index if not exists stock_history_idx on stock_history (stock_id, at desc);

-- Сколько акций у игрока и сколько очков он в них вложил (для P/L).
create table if not exists stock_holdings (
    user_id  bigint not null references players(user_id) on delete cascade,
    stock_id bigint not null references stocks(id) on delete cascade,
    shares   integer not null default 0,
    spent    bigint not null default 0,
    primary key (user_id, stock_id)
);
create index if not exists stock_holdings_user_idx on stock_holdings (user_id);

-- Расписание внезапных пампов: одна строка, когда запускать следующий.
create table if not exists stock_pumps (
    id      integer primary key,
    next_at timestamptz not null default now()
);

insert into stock_pumps (id, next_at)
values (1, now() + interval '30 minutes')
on conflict (id) do nothing;

-- ===================================================================== --
-- Настройки-флажки (например, включилось ли обновление мини-аппок)
-- ===================================================================== --

create table if not exists app_settings (
    key   text primary key,
    value text not null
);


-- ===================================================================== --
-- Рейд-босс
-- ===================================================================== --

create table if not exists boss_raid (
    id          bigserial primary key,
    name        text not null,
    hp          bigint not null,
    max_hp      bigint not null,
    hit_damage  integer not null default 50,
    status      text not null default 'active',
    chat_id     bigint,
    message_id  bigint,
    created_at  timestamptz not null default now(),
    killed_at   timestamptz,
    rewarded_at timestamptz
);
create index if not exists boss_raid_status_idx on boss_raid (status);

-- Вклад каждого игрока: сколько ударов и сколько урона.
create table if not exists boss_hits (
    boss_id    bigint not null references boss_raid(id) on delete cascade,
    user_id    bigint not null,
    hits       integer not null default 0,
    damage     bigint not null default 0,
    updated_at timestamptz not null default now(),
    primary key (boss_id, user_id)
);

-- ===================================================================== --
-- Ивент, счастливые минуты и кликер-копилка
-- ===================================================================== --

create table if not exists game_event (
    id          integer primary key default 1,
    active      boolean not null default false,
    clicker     boolean not null default false,
    happy_until timestamptz,
    happy_boost real not null default 1,
    started_at  timestamptz,
    constraint game_event_single check (id = 1)
);
insert into game_event (id) values (1) on conflict (id) do nothing;

-- Копилка: клики и накопленные очки. Выдаются разом в конце ивента.
create table if not exists kopilka (
    user_id    bigint primary key references players(user_id) on delete cascade,
    clicks     integer not null default 0,
    points     integer not null default 0,
    granted    boolean not null default false,
    updated_at timestamptz not null default now()
);

-- Копилка копит не только очки: крутки, спины, кейсы и карты тоже.
alter table kopilka add column if not exists drops integer not null default 0;
alter table kopilka add column if not exists spins integer not null default 0;
alter table kopilka add column if not exists cases integer not null default 0;
alter table kopilka add column if not exists cards jsonb not null default '[]'::jsonb;

-- Лаки-минута: куда сообщить, когда она закончится.
alter table game_event add column if not exists happy_chat bigint;
alter table game_event add column if not exists happy_announced boolean not null default true;

-- Апгрейдер: журнал круток, чтобы видеть, что и на что меняли.
create table if not exists upgrader_log (
    id         bigserial primary key,
    user_id    bigint not null,
    from_card  text not null,
    to_card    text not null,
    chance     real not null,
    won        boolean not null,
    created_at timestamptz not null default now()
);
create index if not exists upgrader_log_user_idx on upgrader_log (user_id, created_at desc);

-- ===================================================================== --
-- Скупщик
-- ===================================================================== --

create table if not exists buyer_log (
    id         bigserial primary key,
    user_id    bigint not null,
    card_id    text,
    price      integer not null,
    created_at timestamptz not null default now()
);
create index if not exists buyer_log_user_idx on buyer_log (user_id, created_at desc);

-- ===================================================================== --
-- Стили мини-аппок
-- ===================================================================== --

alter table players add column if not exists theme text;

create table if not exists player_themes (
    user_id    bigint not null references players(user_id) on delete cascade,
    theme_id   text not null,
    created_at timestamptz not null default now(),
    primary key (user_id, theme_id)
);

-- ===================================================================== --
-- Деп-коины и дрифт-комбо
-- ===================================================================== --

alter table players add column if not exists dep_coins numeric(18,5) not null default 0;
alter table players add column if not exists drift_streak integer not null default 0;

alter table stocks add column if not exists dep_rate numeric(18,5);
update stocks set dep_rate = 100000 where slug = 'dodep' and dep_rate is null;

-- ===================================================================== --
-- Юга-кликер
-- ===================================================================== --

create table if not exists yugi (
    user_id    bigint primary key references players(user_id) on delete cascade,
    balance    numeric(18,2) not null default 0,
    total      numeric(18,2) not null default 0,
    taps       bigint not null default 0,
    cases      integer not null default 0,
    buildings  jsonb not null default '{}'::jsonb,
    upgrades   jsonb not null default '[]'::jsonb,
    updated_at timestamptz not null default now()
);

alter table yugi add column if not exists tap_tokens numeric(12,3) not null default 30;
alter table yugi add column if not exists tap_window_at timestamptz not null default now();

create table if not exists yugi_flags (
    id         bigserial primary key,
    user_id    bigint not null,
    asked      integer not null,
    accepted   integer not null,
    created_at timestamptz not null default now()
);
create index if not exists yugi_flags_user_idx on yugi_flags (user_id, created_at desc);

-- ===================================================================== --
-- Недельный ивент «Звёздочка»
-- ===================================================================== --

create table if not exists event_week (
    id          integer primary key default 1,
    active      boolean not null default false,
    started_at  timestamptz,
    ends_at     timestamptz,
    title       text
);
insert into event_week (id, active) values (1, false) on conflict (id) do nothing;

create table if not exists event_quests (
    id          bigserial primary key,
    user_id     bigint not null,
    day         integer not null,
    slot        integer not null,
    source      text not null,
    need        integer not null,
    baseline    bigint not null,
    claimed     boolean not null default false,
    created_at  timestamptz not null default now(),
    unique (user_id, day, slot)
);
create index if not exists event_quests_user_idx on event_quests (user_id, day);

create table if not exists event_players (
    user_id       bigint primary key,
    done_count    integer not null default 0,
    main_unlocked boolean not null default false,
    main_done     boolean not null default false,
    given_drops   integer not null default 0,
    given_roulette integer not null default 0,
    main_drops    integer not null default 0,
    main_roulette integer not null default 0,
    main_cases    integer not null default 0,
    main_points   bigint not null default 0,
    joined_at     timestamptz not null default now()
);
alter table event_players add column if not exists last_grant_day integer not null default 0;

create table if not exists case_limits (
    user_id  bigint primary key,
    day      date not null default current_date,
    used     integer not null default 0,
    last_at  timestamptz
);

-- ===================================================================== --
-- Профили игроков
-- ===================================================================== --

create table if not exists profiles (
    user_id    bigint primary key,
    bio        text not null default '',
    status     text not null default '',
    banner     text not null default 'sunset',
    music      text not null default '',
    updated_at timestamptz not null default now()
);

create table if not exists profile_rewards (
    id         bigserial primary key,
    user_id    bigint not null,
    icon       text not null default '🏆',
    text       text not null,
    created_at timestamptz not null default now()
);
create index if not exists profile_rewards_user_idx on profile_rewards (user_id, id);

create table if not exists profile_tags (
    user_id    bigint not null,
    tag        text not null,
    created_at timestamptz not null default now(),
    primary key (user_id, tag)
);


-- Аватарка профиля: ссылка на картинку.
alter table profiles add column if not exists avatar text not null default '';

-- Эльвира за дрифт-комбо: строго один раз за всё время.
alter table players add column if not exists drift_granted boolean not null default false;

-- У кого она уже есть — считаем награду использованной.
update players p set drift_granted = true
 where p.drift_granted = false
   and exists (
       select 1 from collection c
        where c.user_id = p.user_id and c.card_id = 'elvira_drift'
   );

-- Бан: забаненный не может ничего делать ни в боте, ни в приложении.
alter table players add column if not exists banned boolean not null default false;
alter table players add column if not exists ban_reason text;
alter table players add column if not exists banned_at timestamptz;

-- VIP-подписка: срок и отметка последней выдачи дневных бонусов.
alter table players add column if not exists vip_until timestamptz;
alter table players add column if not exists vip_day date;

-- PvP: стрик побед и учёт пар «игрок–игрок» для античита.
alter table players add column if not exists pvp_streak integer not null default 0;

create table if not exists pvp_pairs (
    a_id   bigint not null,
    b_id   bigint not null,
    fights integer not null default 0,
    primary key (a_id, b_id)
);

-- ===== Кликер: здания, апгрейды и фишки престижа =====
create table if not exists yugi_buildings (
    user_id     bigint  not null,
    building_id text    not null,
    count       integer not null default 0,
    primary key (user_id, building_id)
);

create table if not exists yugi_upgrades (
    user_id   bigint not null,
    upgrade_id text  not null,
    primary key (user_id, upgrade_id)
);

alter table players add column if not exists yugi_chips integer not null default 0;
alter table players add column if not exists yugi_resets integer not null default 0;

alter table players add column if not exists yugi_tree jsonb not null default '[]'::jsonb;

-- Золотые печеньки: когда истекает текущая, и активные баффы.
alter table yugi add column if not exists golden_until timestamptz;
alter table yugi add column if not exists frenzy_until timestamptz;
alter table yugi add column if not exists click_until timestamptz;

-- ===================================================================== --
-- Кооп-босс подземелья (/proto_dungeon): один босс на двоих
-- ===================================================================== --

create table if not exists dungeon_boss (
    id          bigserial primary key,
    zone        integer not null default 0,
    hp          bigint  not null,
    max_hp      bigint  not null,
    status      text    not null default 'waiting',
    ready_at    timestamptz not null default now(),
    started_at  timestamptz,
    finished_at timestamptz,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index if not exists dungeon_boss_zone_status_idx
    on dungeon_boss (zone, status);
create index if not exists dungeon_boss_status_updated_idx
    on dungeon_boss (status, updated_at);

create table if not exists dungeon_boss_players (
    boss_id          bigint  not null references dungeon_boss(id) on delete cascade,
    user_id          bigint  not null,
    slot             integer not null default 1,
    hp               integer not null,
    max_hp           integer not null,
    damage           bigint  not null default 0,
    hits             integer not null default 0,
    dead             boolean not null default false,
    left_at          timestamptz,
    last_hit_at      timestamptz,
    last_boss_hit_at timestamptz,
    seen_at          timestamptz not null default now(),
    primary key (boss_id, user_id)
);
create index if not exists dungeon_boss_players_user_idx
    on dungeon_boss_players (user_id, boss_id);


-- ===================================================================== --
-- Подземелье: прогресс героя (уровень, монеты, сумка)
-- ===================================================================== --

create table if not exists dungeon_hero (
    user_id    bigint primary key,
    level      integer not null default 1,
    exp        integer not null default 0,
    coins      bigint  not null default 0,
    kills      integer not null default 0,
    weapon     text,
    bag        jsonb   not null default '[]'::jsonb,
    updated_at timestamptz not null default now()
);

-- ===================================================================== --
-- Квесты со страницы «Задания»: награда забирается один раз
-- ===================================================================== --

create table if not exists quest_claim (
    user_id    bigint not null,
    quest_key  text   not null,
    claimed_at timestamptz not null default now(),
    primary key (user_id, quest_key)
);

alter table dungeon_hero add column if not exists armor integer not null default 0;

-- Последняя точка героя: где он стоял, когда вышел. Из неё же показываем
-- оффлайн-игроков в углу локации и туда же возвращаем при следующем входе.
alter table dungeon_hero add column if not exists zone integer;
alter table dungeon_hero add column if not exists x real;
alter table dungeon_hero add column if not exists y real;
alter table dungeon_hero add column if not exists seen_at timestamptz;
