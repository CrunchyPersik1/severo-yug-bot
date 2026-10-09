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
    updated_at timestamptz not null default now()
);

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
