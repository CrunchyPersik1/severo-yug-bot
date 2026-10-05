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
