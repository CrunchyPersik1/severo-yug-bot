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
